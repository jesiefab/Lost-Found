"""One read path, two backends, and a fallback nobody can mistake for the real thing.

Three rules, in order of importance:

1. A read never fails because the database blinked. It is served from the
   committed snapshot on the request that noticed, not the next one.
2. A write is never faked. Once degraded, writes are refused, and the write
   that tripped the failure reports that its outcome is unknown, because it may
   have committed before the connection dropped.
3. Degradation is sticky until a health probe succeeds. Flapping between two
   corpora mid-demo would make the panel's numbers unauditable.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, TypeVar

from dsa.models import Item

from .protocol import ItemStore, StoreReadOnly, StoreUnavailable

T = TypeVar("T")

# What counts as "the database is gone" rather than "the request was wrong".
# The Supabase store wraps its client's errors into StoreUnavailable; these
# extra types cover sockets that fail before the client can wrap them.
UNAVAILABLE = (StoreUnavailable, TimeoutError, ConnectionError)

READ_ONLY_HINT = "database unreachable — running from the committed snapshot"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _describe(exc: BaseException) -> str:
    return (str(exc).strip() or "database unreachable")[:200]


class StoreFacade:
    """Primary store plus a snapshot fallback that takes over mid-request."""

    def __init__(
        self,
        primary: ItemStore,
        make_fallback: Callable[[str], ItemStore],
    ) -> None:
        self._primary = primary
        self._make_fallback = make_fallback
        self._fallback: ItemStore | None = None
        self._reason: str | None = None
        self._lock = threading.Lock()
        self.degraded_at: str | None = None
        self.recovered_at: str | None = None
        self.degradations = 0
        self.recoveries = 0

    # -- state -----------------------------------------------------------
    @property
    def degraded(self) -> bool:
        return self._reason is not None

    @property
    def source(self) -> str:
        return "snapshot" if self.degraded else self._primary.source

    @property
    def writable(self) -> bool:
        return not self.degraded

    @property
    def state(self) -> dict:
        payload: dict[str, Any] = {
            "source": self.source,
            "writable": self.writable,
            "degraded": self.degraded,
            "reason": self._reason or "",
            "degraded_at": self.degraded_at,
            "recovered_at": self.recovered_at,
            "degradations": self.degradations,
            "recoveries": self.recoveries,
        }
        if self._fallback is not None:
            payload["backup"] = self._fallback.state
        return payload

    def _degrade(self, exc: BaseException) -> ItemStore:
        """Flip to the snapshot once, and return the store to read from."""
        with self._lock:
            if self._reason is None:
                self._reason = _describe(exc)
                self.degraded_at = _now()
                self.degradations += 1
                self._fallback = self._make_fallback(self._reason)
            assert self._fallback is not None
            return self._fallback

    def _recover(self) -> None:
        with self._lock:
            if self._reason is None:
                return
            self._reason = None
            self._fallback = None
            self.recovered_at = _now()
            self.recoveries += 1

    def _fallback_store(self) -> ItemStore:
        assert self._fallback is not None, "degraded without a fallback"
        return self._fallback

    # -- reads -----------------------------------------------------------
    def _read(self, operation: Callable[[ItemStore], T]) -> T:
        if self.degraded:
            return operation(self._fallback_store())
        try:
            return operation(self._primary)
        except UNAVAILABLE as exc:
            return operation(self._degrade(exc))

    def list_items(self) -> list[Item]:
        return self._read(lambda store: store.list_items())

    def get(self, item_id: int) -> Item | None:
        return self._read(lambda store: store.get(item_id))

    # -- writes: refused, never faked ------------------------------------
    def _write(self, operation: Callable[[ItemStore], T]) -> T:
        if self.degraded:
            raise StoreReadOnly(self._reason or READ_ONLY_HINT)
        try:
            return operation(self._primary)
        except UNAVAILABLE as exc:
            self._degrade(exc)
            raise StoreReadOnly(
                self._reason or READ_ONLY_HINT, outcome_unknown=True
            ) from exc

    def insert(self, item: Item) -> Item:
        return self._write(lambda store: store.insert(item))

    def update(
        self, item_id: int, changes: Mapping[str, Any], owner_token: str
    ) -> Item:
        return self._write(lambda store: store.update(item_id, changes, owner_token))

    def delete(self, item_id: int, owner_token: str) -> Item:
        return self._write(lambda store: store.delete(item_id, owner_token))

    def clear_samples(self) -> int:
        return self._write(lambda store: store.clear_samples())

    # -- the retry button ------------------------------------------------
    def health(self, force: bool = False) -> dict:
        """Probe the primary and report state.

        A store that answers ``False`` is exactly as unusable as one that
        raises, so the bool is honoured rather than discarded.
        """
        if self.degraded and not force:
            return self.state
        try:
            healthy = self._primary.health()
        except UNAVAILABLE as exc:
            self._degrade(exc)
            return self.state
        if healthy is False:
            self._degrade(StoreUnavailable("database health check failed"))
            return self.state
        self._recover()
        return self.state

    def probe(self, force: bool = False) -> dict:
        return self.health(force=force)

    def close(self) -> None:
        self._primary.close()
        if self._fallback is not None:
            self._fallback.close()
