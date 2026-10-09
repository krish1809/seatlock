"""In-process counters, exposed at GET /metrics.

The api runs as one uvicorn process, so plain counters are enough; the lock is
needed because endpoints run in many worker threads at once.
"""
import threading
from collections import Counter

_lock = threading.Lock()
_counters: Counter = Counter()


def inc(name: str, n: int = 1) -> None:
    with _lock:
        _counters[name] += n


def snapshot() -> dict:
    with _lock:
        return dict(sorted(_counters.items()))
