"""The seam between the algorithms and wherever the rows live.

`dsa/` never imports from here and nothing here imports the search engine: a
store returns `Item`s, the engine derives tokens from them, and the algorithms
cannot tell which store produced the list. That is what makes the fallback a
different loader rather than a second search.

Validation lives here too, so both stores reject the same bad input with the
same message instead of each inventing its own rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any, Protocol, runtime_checkable

from dsa.models import KINDS, STATUSES, Item

# Client-editable columns. `id`, `created_at`, `owner_token` and `is_sample`
# are deliberately absent: ownership is proven, not asserted, and sample rows
# are cleared by an explicit action rather than a PATCH.
EDITABLE_FIELDS = (
    "kind",
    "title",
    "description",
    "category",
    "location",
    "date_iso",
    "status",
    "reporter",
    "tags",
)

MAX_TITLE = 160
MAX_TEXT = 2000


class StoreError(Exception):
    """Anything the API should turn into a 4xx/5xx with a readable message."""


class StoreUnavailable(StoreError):
    """The backend could not be reached or answered with a server error.

    Raised by a store, caught by the facade, which is what flips the app to
    the snapshot. Nothing else should catch it.
    """


class StoreReadOnly(StoreError):
    """A write was refused because the store is degraded.

    `outcome_unknown` is True only for the write that tripped the failure: that
    row may or may not have committed before the connection dropped, and the
    caller is expected to say so rather than retrying silently.
    """

    def __init__(self, reason: str, *, outcome_unknown: bool = False) -> None:
        self.reason = reason
        self.outcome_unknown = outcome_unknown
        super().__init__(reason)


class ItemNotFound(StoreError):
    pass


class NotOwner(StoreError):
    pass


class ValidationError(StoreError):
    pass


def drop_tokens(item: Item) -> Item:
    """Stores hold columns, not derived state; the engine tokenizes on load."""
    return item.with_tokens(())


def normalize_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw: list[Any] = value.split(",")
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        raise ValidationError("tags must be a list of strings")
    unique: dict[str, None] = {}
    for tag in raw:
        text = str(tag).strip()
        if not text:
            continue
        if len(text) > 40:
            raise ValidationError("a tag cannot be longer than 40 characters")
        unique.setdefault(text, None)
    return tuple(unique)


def _text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    text = value.strip()
    if len(text) > limit:
        raise ValidationError(f"{field} is longer than {limit} characters")
    return text


def _iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError("date_iso is required")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValidationError("date_iso must be a date like 2026-11-23") from exc


def validate_patch(changes: Mapping[str, Any]) -> dict[str, Any]:
    """Clean a partial update. Unknown or non-editable fields are refused."""
    if not isinstance(changes, Mapping):
        raise ValidationError("changes must be an object")

    clean: dict[str, Any] = {}
    for field, value in changes.items():
        if field not in EDITABLE_FIELDS:
            raise ValidationError(f"{field} is not an editable field")
        if field == "kind":
            if value not in KINDS:
                raise ValidationError("kind must be 'lost' or 'found'")
            clean["kind"] = value
        elif field == "status":
            if value not in STATUSES:
                raise ValidationError("status must be 'open', 'claimed' or 'returned'")
            clean["status"] = value
        elif field == "tags":
            clean["tags"] = normalize_tags(value)
        elif field == "date_iso":
            clean["date_iso"] = _iso_date(value)
        elif field == "title":
            clean["title"] = _text(value, field, MAX_TITLE)
        else:
            clean[field] = _text(value, field)

    if "title" in clean and not clean["title"]:
        raise ValidationError("title cannot be empty")
    return clean


def validate_new(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Clean a whole record. Same rules as an update, plus the required parts."""
    clean = validate_patch(fields)
    if "kind" not in clean:
        raise ValidationError("kind is required ('lost' or 'found')")
    if "date_iso" not in clean:
        raise ValidationError("date_iso is required")
    if not clean.get("title"):
        raise ValidationError("title is required")
    clean.setdefault("description", "")
    clean.setdefault("category", "other")
    clean.setdefault("location", "")
    clean.setdefault("status", "open")
    clean.setdefault("reporter", "")
    clean.setdefault("tags", ())
    return clean


def fields_of(item: Item) -> dict[str, Any]:
    """The editable view of an Item, for validate_new on an insert."""
    return {field: getattr(item, field) for field in EDITABLE_FIELDS}


@runtime_checkable
class ItemStore(Protocol):
    """What both stores guarantee. The facade and the API type against this."""

    source: str
    writable: bool

    @property
    def state(self) -> dict: ...

    def list_items(self) -> list[Item]: ...

    def get(self, item_id: int) -> Item | None: ...

    def insert(self, item: Item) -> Item: ...

    def update(
        self, item_id: int, changes: Mapping[str, Any], owner_token: str
    ) -> Item: ...

    def delete(self, item_id: int, owner_token: str) -> Item: ...

    def clear_samples(self) -> int: ...

    def health(self) -> bool: ...

    def close(self) -> None: ...
