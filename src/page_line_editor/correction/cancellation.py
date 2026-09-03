"""Cooperative cancellation primitives independent of Qt."""

from __future__ import annotations

from threading import Event


class CorrectionCancelled(RuntimeError):
    """Raised when a correction operation observes cancellation."""


class CancellationToken:
    def __init__(self) -> None:
        """Initialize the CancellationToken instance."""
        self._event = Event()

    def cancel(self) -> None:
        """Discard uncommitted overlay text and restore the selected line."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation was requested."""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise if cancelled."""
        if self.cancelled:
            raise CorrectionCancelled("Automatic correction was cancelled")


class NullCancellationToken(CancellationToken):
    """A token that cannot be cancelled."""

    def cancel(self) -> None:
        """Discard uncommitted overlay text and restore the selected line."""
        return None
