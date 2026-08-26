"""Cooperative cancellation primitives independent of Qt."""

from __future__ import annotations

from threading import Event


class CorrectionCancelled(RuntimeError):
    """Raised when a correction operation observes cancellation."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CorrectionCancelled("Automatic correction was cancelled")


class NullCancellationToken(CancellationToken):
    """A token that cannot be cancelled."""

    def cancel(self) -> None:
        return None
