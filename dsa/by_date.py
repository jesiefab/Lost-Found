"""Sorted-by-date list of item ids, maintained by binary-search insertion.

Browse and date-range filters come from here: the newest-first order is this
structure's job, not the index's, and the binary search is the honest
textbook use of a sorted list.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import inf
from typing import Iterable


class SortedByDate:
    def __init__(self, pairs: Iterable[tuple[str, int]] = ()) -> None:
        self._keys: list[tuple[str, int]] = []
        self._ids: list[int] = []
        for date_iso, item_id in pairs:
            self.insert(item_id, date_iso)

    # -- writes ---------------------------------------------------------
    def insert(self, item_id: int, date_iso: str) -> None:
        key = (date_iso, item_id)
        at = bisect_right(self._keys, key)
        self._keys.insert(at, key)
        self._ids.insert(at, item_id)

    def remove(self, item_id: int, date_iso: str) -> int:
        """Splice the id out; returns how many entries shifted left."""
        key = (date_iso, item_id)
        at = bisect_left(self._keys, key)
        if at < len(self._keys) and self._keys[at] == key:
            self._keys.pop(at)
            self._ids.pop(at)
            return len(self._ids) - at
        return 0

    # -- reads ----------------------------------------------------------
    def newest_first(self) -> list[int]:
        return list(reversed(self._ids))

    def between(self, start: str | None = None, end: str | None = None) -> list[int]:
        """Ids whose date falls in [start, end]; either bound may be missing."""
        low = 0 if start is None else bisect_left(self._keys, (start, 0))
        high = len(self._keys) if end is None else bisect_right(self._keys, (end, inf))
        return self._ids[low:high]

    def __len__(self) -> int:
        return len(self._ids)
