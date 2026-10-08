"""The interface every hold strategy implements."""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HoldResult:
    success: bool
    held: list[int] = field(default_factory=list)
    unavailable: list[int] = field(default_factory=list)
    held_until: datetime | None = None


class HoldStrategy(ABC):
    name: str
    # Isolation level for the transaction the service opens around hold().
    # None means the server default, READ COMMITTED.
    isolation_level: str | None = None

    @abstractmethod
    def hold(self, conn, event_id: int, seat_ids: list[int], user_id: int) -> HoldResult:
        """Try to hold every seat in seat_ids (sorted, distinct) for user_id.

        Runs inside the caller's transaction. When a seat is not free it returns
        success=False rather than raising; the caller then rolls the whole
        transaction back, which makes a multi-seat hold all-or-nothing.
        A seat is free when it is AVAILABLE or its hold has expired.
        """


def hold_seconds() -> int:
    # Read on every call so tests can shorten holds with monkeypatch.setenv.
    return int(os.environ.get("HOLD_SECONDS", "300"))
