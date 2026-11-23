"""Inverted index: term -> ascending posting list of item ids.

Posting lists are kept sorted so intersecting two tokens is a merge walk and
removing an item is a bisect plus a pop — no rebuilding, no tombstones.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Iterable


class InvertedIndex:
    def __init__(self) -> None:
        self._postings: dict[str, list[int]] = {}

    # -- writes ---------------------------------------------------------
    def add(self, item_id: int, tokens: Iterable[str]) -> None:
        for term in tokens:
            postings = self._postings.setdefault(term, [])
            at = bisect_left(postings, item_id)
            if at == len(postings) or postings[at] != item_id:
                postings.insert(at, item_id)

    def remove(self, item_id: int, tokens: Iterable[str]) -> int:
        """Drop the id from every term it carried.

        Returns the number of postings entries scanned (sum of the touched
        document frequencies) — the visible price of a delete, reported by
        the panel rather than left as a claim.
        """
        scanned = 0
        for term in tokens:
            postings = self._postings.get(term)
            if not postings:
                continue
            scanned += len(postings)
            at = bisect_left(postings, item_id)
            if at < len(postings) and postings[at] == item_id:
                postings.pop(at)
            if not postings:
                del self._postings[term]
        return scanned

    # -- reads ----------------------------------------------------------
    def postings(self, term: str) -> tuple[int, ...]:
        return tuple(self._postings.get(term, ()))

    def terms(self) -> tuple[str, ...]:
        return tuple(self._postings)

    def document_frequency(self, term: str) -> int:
        return len(self._postings.get(term, ()))

    def __contains__(self, term: object) -> bool:
        return term in self._postings

    def __len__(self) -> int:
        return len(self._postings)

    @property
    def term_count(self) -> int:
        return len(self._postings)

    @property
    def posting_count(self) -> int:
        return sum(len(postings) for postings in self._postings.values())
