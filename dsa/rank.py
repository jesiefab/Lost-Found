"""Insertion-sort ranking: most matched query tokens first, then newest.

Insertion sort on purpose — the result list is short (it is the candidate set
the index narrowed to), and a hand-written sort is something to defend. The
comparison and shift counts are returned so the panel can show the cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .models import Item


@dataclass(frozen=True)
class SortStats:
    comparisons: int
    shifts: int


def _outranks(left: Item, right: Item, counts: Mapping[int, int]) -> int:
    """1 if `left` sorts before `right`, -1 after, 0 tied on every key."""
    left_hits = counts.get(left.id, 0)
    right_hits = counts.get(right.id, 0)
    if left_hits != right_hits:
        return 1 if left_hits > right_hits else -1
    if left.date_iso != right.date_iso:
        return 1 if left.date_iso > right.date_iso else -1
    if left.id != right.id:
        return 1 if left.id > right.id else -1
    return 0


def sort_ranked(
    items: Iterable[Item], counts: Mapping[int, int]
) -> tuple[list[Item], SortStats]:
    ordered: list[Item] = list(items)
    comparisons = 0
    shifts = 0
    for index in range(1, len(ordered)):
        current = ordered[index]
        cursor = index - 1
        while cursor >= 0:
            comparisons += 1
            if _outranks(current, ordered[cursor], counts) > 0:
                ordered[cursor + 1] = ordered[cursor]
                shifts += 1
                cursor -= 1
            else:
                break
        ordered[cursor + 1] = current
    return ordered, SortStats(comparisons=comparisons, shifts=shifts)
