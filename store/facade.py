"""One read path, two backends, and a fallback nobody can mistake for the real thing.

Three rules, in order of importance:

1. A read never fails because the database blinked. It is served from the
   committed snapshot instead, on the request that noticed — not the next one.
2. A write is never faked. Once degraded, writes are refused with a reason, and
   the write that tripped the failure reports that its outcome is unknown,
   because it may have committed before the connection dropped.
3. Degradation is sticky until a health probe succeeds. Flapping between two
   corpora mid-demo would make the panel's numbers unauditable, which is worse
   than a visible outage.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from dsa.models import Item

from .protocol import (
    ItemStore,
    StoreReadOnly,
    StoreUnavailable,
)

# What counts as "the database is gone" rather than "the request was wrong".
# The Supabase store wraps its client's errors into StoreUnavailable; these
# extra types cover sockets that fail before the client can wrap them.
UNAVAILABLE = (StoreUnavailable, TimeoutError, ConnectionError)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _describe(exc: BaseException) -> str:
    message = str(exc).strip() or "database unreachable"
    return message[:200]


class StoreFacade:
    """Primary store plus a snapshot fallback that takes over mid-request."""

    def __init__(
        self,
        primary: ItemStore,
        make_fallback: Callable[[str], ItemStore],
        *,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._primary = primary
        self._make_fallback = make_fallback
        self._clock = clock
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
                self.degraded_at = self._clock()
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
            self.recovered_at = self._clock()
            self.recoveries += 1

    def _refuse_write(self) -> None:
        if self.degraded:
            raise StoreReadOnly(_describe_reason(self._reason))

    # -- reads -----------------------------------------------------------
    def list_items(self) -> list[Item]:
        if self.degraded:
            return self._fallback_items().list_items()
        try:
            return self._primary.list_items()
        except UNAVAILABLE as exc:
            return self._degrade(exc).list_items()

    def get(self, item_id: int) -> Item | None:
        if self.degraded:
            return self._fallback_items().get(item_id)
        try:
            return self._primary.get(item_id)
        except UNAVAILABLE as exc:
            return self._degrade(exc).get(item_id)

    # -- writes: refused, never faked ------------------------------------
    def insert(self, item: Item) -> Item:
        self._refuse_write()
        try:
            return self._primary.insert(item)
        except UNAVAILABLE as exc:
            self._degrade(exc)
            raise StoreReadOnly(_describe_reason(self._reason), outcome_unknown=True) from exc

    def update(
        self, item_id: int, changes: Mapping[str, Any], owner_token: str
    ) -> Item:
        self._refuse_write()
        try:
            return self._primary.update(item_id, changes, owner_token)
        except UNAVAILABLE as exc:
            self._degrade(exc)
            raise StoreReadOnly(_describe_reason(self._reason), outcome_unknown=True) from exc

    def delete(self, item_id: int, owner_token: str) -> Item:
        self._refuse_write()
        try:
            return self._primary.delete(item_id, owner_token)
        except UNAVAILABLE as exc:
            self._degrade(exc)
            raise StoreReadOnly(_describe_reason(self._reason), outcome_unknown=True) from exc

    def clear_samples(self) -> int:
        self._refuse_write()
        try:
            return self._primary.clear_samples()
        except UNAVAILABLE as exc:
            self._degrade(exc)
            raise StoreReadOnly(_describe_reason(self._reason), outcome_unknown=True) from exc

    # -- the retry button ------------------------------------------------
    def health(self, force: bool = False) -> dict:
        """Probe the primary. A store that answers False is as unusable as one
        that raises — the bool is the contract, so it is honoured, not stored."""
        if not self.degraded:
            try:
                healthy = self._primary.health()
            except UNAVAILABLE as exc:
                self._degrade(exc)
                return self.state
            if healthy is False:
                self._degrade(StoreUnavailable("database health check failed"))
            return self.state

        if not force:
            return self.state

        try:
            healthy = self._primary.health()
        except UNAVAILABLE as exc:
            with self._lock:
                self._reason = _describe(exc)
            return self.state

        if healthy is False:
            with self._lock:
                self._reason = "database health check failed"
            return self.state

        self._recover()
        return self.state

    def close(self) -> None:
        self._primary.close()
        if self._fallback is not None:
            self._fallback.close()

    # -- internals -------------------------------------------------------
    def _fallback_items(self) -> ItemStore:
        if self._fallback is None:
            # Defensive: degraded without a fallback should be impossible, but
            # a read path that 500s is exactly what this class exists to avoid.
            return self._degrade(StoreUnavailable("database unreachable"))
        return self._fallback


def _describe_reason(reason: str | None) -> str:
    if reason:
        return reason
    return "database unreachable — running from the committed snapshot"
