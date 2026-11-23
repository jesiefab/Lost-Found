"""Item: the one shape the table, the snapshot and the algorithms agree on.

`tokens` is derived, never stored. It is filled once when a corpus loads
(`SearchEngine.add`), so the indexed path and the linear scan read the
identical list and cannot drift apart through a second tokenizer call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

KINDS = ("lost", "found")
STATUSES = ("open", "claimed", "returned")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    title: str
    description: str = ""
    category: str = "other"
    location: str = ""
    date_iso: str = ""
    status: str = "open"
    reporter: str = ""
    tags: tuple[str, ...] = ()
    is_sample: bool = False
    owner_token: str = ""

    # Derived in memory at load. Not a column, not in the snapshot.
    tokens: tuple[str, ...] = ()

    def with_tokens(self, tokens: Iterable[str]) -> "Item":
        return replace(self, tokens=tuple(tokens))

    def searchable_text(self) -> str:
        """Everything the tokenizer reads. One function, both paths.

        Location is included so "gym" finds items left at the gym even when
        the post itself never names the place.
        """
        parts = [
            self.title,
            self.description,
            self.category,
            self.location,
            " ".join(self.tags),
        ]
        return " ".join(part for part in parts if part)

    def to_row(self) -> dict[str, Any]:
        """The database / snapshot shape: derived fields dropped."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "location": self.location,
            "date_iso": self.date_iso,
            "status": self.status,
            "reporter": self.reporter,
            "tags": list(self.tags),
            "is_sample": self.is_sample,
            "owner_token": self.owner_token,
        }

    def to_public(self) -> dict[str, Any]:
        """What the browser sees: no owner token and no derived tokens.

        Dropping `tokens` matters on the wire as well as in principle — a
        275-item result set would otherwise carry a token list per item.
        """
        row = self.to_row()
        row.pop("owner_token", None)
        return row

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Item":
        tags = row.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = [tags]

        date_iso = row.get("date_iso")
        if date_iso is not None and not isinstance(date_iso, str):
            date_iso = date_iso.isoformat() if hasattr(date_iso, "isoformat") else str(date_iso)

        return cls(
            id=int(row["id"]),
            kind=_text(row.get("kind")) or "lost",
            title=_text(row.get("title")),
            description=_text(row.get("description")),
            category=_text(row.get("category")) or "other",
            location=_text(row.get("location")),
            date_iso=_text(date_iso),
            status=_text(row.get("status")) or "open",
            reporter=_text(row.get("reporter")),
            tags=tuple(str(tag) for tag in tags),
            is_sample=bool(row.get("is_sample")),
            owner_token=_text(row.get("owner_token")),
        )
