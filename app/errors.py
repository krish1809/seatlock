"""Domain errors raised by services; app/main.py maps them to HTTP responses."""


class Conflict(Exception):
    """409: the request is valid but the current state does not allow it."""

    def __init__(self, message: str, seat_ids: list[int] | None = None):
        super().__init__(message)
        self.message = message
        self.seat_ids = seat_ids or []


class NotFound(Exception):
    """404"""
