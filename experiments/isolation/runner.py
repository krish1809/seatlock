"""Run scripted, interleaved steps on two connections at a chosen isolation level.

Each scenario is a list of steps (session, SQL). The runner sends one step at a
time and waits until that statement has either finished or is blocked on a lock
(checked with pg_blocking_pids() from a third, monitor connection). Ordering is
therefore explicit: no step depends on sleep-based timing.

Usage: python experiments/isolation/runner.py   (or `make isolation`)
Writes docs/isolation-results.md from the actual runs. Reseeds the dev database.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psycopg

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"]
STEP_TIMEOUT_S = 10


@dataclass
class Step:
    session: str                  # "T1" or "T2"
    sql: str | Callable           # SQL text, or ctx -> (sql, params) built from earlier results
    key: str | None = None        # store this step's rows in ctx[key]
    note: str = ""


class Session:
    """One connection driven by one thread, so its statements run in order."""

    def __init__(self, name: str):
        self.name = name
        # autocommit=True: the scenario's own BEGIN / COMMIT statements are sent
        # exactly as written, as you would type them into psql.
        self.conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
        self.pid = self.conn.info.backend_pid
        self.thread = ThreadPoolExecutor(max_workers=1)

    def submit(self, sql, params):
        return self.thread.submit(self._execute, sql, params)

    def _execute(self, sql, params):
        try:
            cur = self.conn.execute(sql, params)
            rows = cur.fetchall() if cur.description else None
            return {"ok": True, "rows": rows, "status": cur.statusmessage}
        except psycopg.Error as e:
            return {"ok": False, "sqlstate": e.sqlstate, "error": e.diag.message_primary}

    def close(self):
        self.thread.shutdown()
        self.conn.close()


def is_blocked(monitor, pid) -> bool:
    return bool(monitor.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0])


def settle(fut, session, monitor) -> str:
    """Wait until the statement finished ("done") or is waiting on a lock ("blocked")."""
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        if fut.done():
            return "done"
        if is_blocked(monitor, session.pid):
            return "blocked"
        try:
            fut.result(timeout=0.005)
        except TimeoutError:
            pass
    raise RuntimeError(f"{session.name} neither finished nor blocked within {STEP_TIMEOUT_S}s")


def describe(result) -> str:
    if not result["ok"]:
        return f"ERROR {result['sqlstate']}: {result['error']}"
    if result["rows"] is not None:
        return "; ".join(", ".join(str(v) for v in row) for row in result["rows"]) or "(no rows)"
    return result["status"]


def run_scenario(scenario, level: str) -> dict:
    """Run one scenario module at one isolation level; return its transcript and outcome."""
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as monitor:
        with monitor.transaction():
            monitor.execute((ROOT / "db" / "seed" / "seed_small.sql").read_text())
            if getattr(scenario, "SETUP_SQL", None):
                monitor.execute(scenario.SETUP_SQL)

        sessions = {"T1": Session("T1"), "T2": Session("T2")}
        transcript, ctx, pending = [], {}, []
        try:
            for n, step in enumerate(scenario.steps(level), start=1):
                sql, params = step.sql(ctx) if callable(step.sql) else (step.sql, ())
                session = sessions[step.session]
                entry = {"n": n, "session": step.session, "sql": " ".join(sql.split()),
                         "params": params, "note": step.note}
                transcript.append(entry)
                fut = session.submit(sql, params)
                pending.append((entry, step, session, fut))

                # Let every outstanding statement (this one, and any that an
                # earlier step unblocked) reach "done" or "blocked" before moving on.
                still_pending = []
                for p_entry, p_step, p_session, p_fut in pending:
                    if settle(p_fut, p_session, monitor) == "blocked":
                        p_entry.setdefault("blocked_at", n)
                        still_pending.append((p_entry, p_step, p_session, p_fut))
                        continue
                    result = p_fut.result()
                    p_entry["result"] = result
                    if p_step.key:
                        ctx[p_step.key] = result
                pending = still_pending
            if pending:
                raise RuntimeError("scenario ended with statements still blocked")
            outcome = classify(transcript, scenario.judge(ctx, monitor))
        finally:
            for s in sessions.values():
                s.close()
    return {"level": level, "transcript": transcript, "outcome": outcome}


def classify(transcript, anomaly: bool) -> str:
    """aborted (SQLSTATE) if Postgres killed a transaction, else anomaly / prevented."""
    for entry in transcript:
        result = entry["result"]
        if not result["ok"] and result["sqlstate"] in ("40001", "40P01"):
            return f"transaction aborted ({result['sqlstate']})"
    return "anomaly occurred" if anomaly else "prevented"


def render(results: dict) -> str:
    lines = [
        "# Isolation experiment results",
        "",
        "Generated by `python experiments/isolation/runner.py` (`make isolation`) from actual runs on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Do not edit by hand.",
        "",
        "| Scenario | " + " | ".join(LEVELS) + " |",
        "| --- | " + " | ".join("---" for _ in LEVELS) + " |",
    ]
    for name, (scenario, runs) in results.items():
        lines.append(f"| {name} | " + " | ".join(r["outcome"] for r in runs) + " |")
    lines += ["", "Each scenario's rule and the exact steps each transaction ran, with what it saw:", ""]
    for name, (scenario, runs) in results.items():
        lines += [f"## {name}", "", scenario.__doc__.strip(), ""]
        for run in runs:
            lines += [f"<details><summary>{run['level']}: <b>{run['outcome']}</b></summary>", "",
                      "| # | Tx | Statement | Result |", "| --- | --- | --- | --- |"]
            for e in run["transcript"]:
                result = describe(e["result"]).replace("|", "\\|")
                if "blocked_at" in e:
                    result = f"blocked (waiting for a lock), then: {result}"
                sql = e["sql"].replace("|", "\\|")
                params = f" with {tuple(e['params'])}" if e["params"] else ""
                note = f" *({e['note']})*" if e["note"] else ""
                lines.append(f"| {e['n']} | {e['session']} | `{sql}`{params}{note} | {result} |")
            lines += ["", "</details>", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    import lost_update
    import non_repeatable_read
    import write_skew

    results = {}
    for name, module in [("Lost update", lost_update), ("Non-repeatable read", non_repeatable_read),
                         ("Write skew", write_skew)]:
        runs = [run_scenario(module, level) for level in LEVELS]
        results[name] = (module, runs)
        print(f"{name:22} " + " | ".join(f"{r['level']}: {r['outcome']}" for r in runs))

    out = ROOT / "docs" / "isolation-results.md"
    out.write_text(render(results))
    print(f"wrote {out.relative_to(ROOT)}")
