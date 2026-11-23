"""The committed 500 rows, served from disk.

Two uses, one class: `writable=True` is the deliberate offline demo (writes
live in memory and die with the process, which the banner says out loud), and
`writable=False` is the degraded mode the facade switches to when the database
is unreachable — there, a write is refused rather than invented, because the
real database may already hold it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from dsa.models import Item

from .protocol import (
    ItemNotFound,
    NotOwner,
    StoreReadOnly,
    ValidationError,
    drop_tokens,
    fields_of,
    validate_new,
    validate_patch,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = ROOT / "data" / "snapshot.json"


class SnapshotStore:
    source = "snapshot"

    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]] | None = None,
        *,
        writable: bool = True,
        reason: str = "offline demo",
    ) -> None:
        self.writable = writable
        self._reason = reason
        self.meta: dict[str, Any] = {}

        if rows is None:
            payload = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
            rows = payload.get("rows") or []
            self.meta = {
                key: payload.get(key) for key in ("seed_version", "seed", "count", "sha256")
            }
            declared = self.meta.get("count")
            if declared is not None and declared != len(payload.get("rows") or []):
                raise ValidationError("snapshot count does not match its rows")

        self._items: dict[int, Item] = {}
        for row in rows:
            item = drop_tokens(Item.from_row(row))
            self._items[item.id] = item
        self._next_id = (max(self._items) if self._items else 0) + 1

    # -- state -----------------------------------------------------------
    @property
    def state(self) -> dict:
        return {
            "source": self.source,
            "writable": self.writable,
            "degraded": not self.writable,
            "reason": self._reason,
            "rows": len(self._items),
            "snapshot": {
                key: self.meta.get(key) for key in ("seed_version", "count", "sha256")
            },
        }

    def health(self, force: bool = False) -> bool:
        return True

    def probe(self, force: bool = False) -> dict:
        return self.state

    def close(self) -> None:
        return None

    # -- reads -----------------------------------------------------------
    def list_items(self) -> list[Item]:
        return [self._items[item_id] for item_id in sorted(self._items)]

    def get(self, item_id: int) -> Item | None:
        try:
            return self._items.get(int(item_id))
        except (TypeError, ValueError):
            return None

    # -- writes ----------------------------------------------------------
    def _require_writable(self) -> None:
        if not self.writable:
            raise StoreReadOnly(self._reason)

    def insert(self, item: Item) -> Item:
        self._require_writable()
        if not item.owner_token:
            raise ValidationError("owner_token is required")
        clean = validate_new(fields_of(item))
        item_id = self._next_id
        self._next_id += 1
        created = drop_tokens(replace(item, id=item_id, **clean))
        self._items[item_id] = created
        return created

    def update(
        self, item_id: int, changes: Mapping[str, Any], owner_token: str
    ) -> Item:
        self._require_writable()
        item = self.get(item_id)
        if item is None:
            raise ItemNotFound(f"item {item_id} does not exist")
        if not owner_token or owner_token != item.owner_token:
            raise NotOwner("owner token does not match this item")
        clean = validate_patch(changes)
        if not clean:
            return item
        self._items[item.id] = drop_tokens(replace(item, **clean))
        return self._items[item.id]

    def delete(self, item_id: int, owner_token: str) -> Item:
        self._require_writable()
        item = self.get(item_id)
        if item is None:
            raise ItemNotFound(f"item {item_id} does not exist")
        if not owner_token or owner_token != item.owner_token:
            raise NotOwner("owner token does not match this item")
        del self._items[item.id]
        return item

    def clear_samples(self) -> int:
        self._require_writable()
        doomed = [item_id for item_id, item in self._items.items() if item.is_sample]
        for item_id in doomed:
            del self._items[item_id]
        return len(doomed)
