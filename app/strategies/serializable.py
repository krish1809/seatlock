"""Serializable: the naive read-then-write code, run at SERIALIZABLE.

How it prevents double booking: the code is exactly naive.py's; only the
isolation level differs. Under SERIALIZABLE, Postgres (Serializable Snapshot
Isolation) tracks what each transaction read. If two transactions both read a
seat as free and both write it, one of them is aborted with SQLSTATE 40001
instead of committing. The service wraps every attempt in with_retries; the
retry starts with a new snapshot, sees the seat HELD, and fails cleanly.

For two writers of the same row the abort usually comes even earlier, as
"could not serialize access due to concurrent update": at REPEATABLE READ and
above a transaction may not overwrite a row version committed after its
snapshot was taken.

Cost: aborted work and retries under contention, plus SSI bookkeeping
(predicate locks) on every read. In exchange, correctness does not depend on
the application code being written carefully.
"""
from app.strategies.naive import NaiveStrategy


class SerializableStrategy(NaiveStrategy):
    name = "serializable"
    isolation_level = "SERIALIZABLE"
