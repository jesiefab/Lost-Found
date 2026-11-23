"""The query path: one matching rule, two implementations, both measured.

The scan runs on every query even when the index has the answer. That costs a
full pass per search and buys the thing this project is actually about: the
result sets are compared before the response leaves, and a disagreement is
returned and rendered rather than swallowed.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .by_date import SortedByDate
from .inverted import InvertedIndex
from .models import Item
from .rank import SortStats, sort_ranked
from .tokenize import tokenize
from .trie import Trie

TIMING_RUNS = 20


@dataclass(frozen=True)
class Filters:
    category: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    def is_empty(self) -> bool:
        return not any((self.category, self.status, self.date_from, self.date_to))


@dataclass(frozen=True)
class PathMetrics:
    """One path's numbers. `diagnostics` are native to that path only."""

    items_examined: int
    compute_ms: float
    diagnostics: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "items_examined": self.items_examined,
            "compute_ms": round(self.compute_ms, 4),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass
class SearchResult:
    query: str
    tokens: tuple[str, ...]
    mode: str  # "search" | "browse"
    ids: list[int]
    items: list[Item]
    indexed: PathMetrics | None
    linear: PathMetrics | None
    equal: bool | None
    only_indexed: list[int]
    only_linear: list[int]
    corpus_size: int
    index_stats: dict
    sort: SortStats | None = None
    note: str = ""

    @property
    def ratio_items(self) -> float | None:
        if not self.indexed or not self.linear:
            return None
        if self.indexed.items_examined == 0:
            return None
        return self.linear.items_examined / self.indexed.items_examined

    @property
    def ratio_time(self) -> float | None:
        if not self.indexed or not self.linear or self.indexed.compute_ms <= 0:
            return None
        return self.linear.compute_ms / self.indexed.compute_ms

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "tokens": list(self.tokens),
            "mode": self.mode,
            "note": self.note,
            "corpus_size": self.corpus_size,
            "count": len(self.ids),
            "ids": self.ids,
            "items": [item.to_public() for item in self.items],
            "indexed": None if self.indexed is None else self.indexed.to_dict(),
            "linear": None if self.linear is None else self.linear.to_dict(),
            "ratio": {
                "items": None if self.ratio_items is None else round(self.ratio_items, 2),
                "time": None if self.ratio_time is None else round(self.ratio_time, 2),
            },
            "equal": self.equal,
            "mismatch": {"only_indexed": self.only_indexed, "only_linear": self.only_linear},
            "index_stats": self.index_stats,
            "sort": None
            if self.sort is None
            else {"comparisons": self.sort.comparisons, "shifts": self.sort.shifts},
        }


@dataclass
class AuditReport:
    queries: int
    compared: int
    mismatches: list[dict]
    corpus_size: int
    index_stats: dict

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "queries": self.queries,
            "compared": self.compared,
            "mismatches": self.mismatches,
            "corpus_size": self.corpus_size,
            "index_stats": self.index_stats,
        }


class SearchEngine:
    """The corpus plus its three structures. Rebuilt when the rows change."""

    def __init__(self, items: Iterable[Item] = ()) -> None:
        self._items: dict[int, Item] = {}
        self._index = InvertedIndex()
        self._trie = Trie()
        self._by_date = SortedByDate()
        started = time.perf_counter()
        for item in items:
            self.add(item)
        self.build_ms = (time.perf_counter() - started) * 1000.0

    # -- writes: the rubric's insert / update / delete --------------------
    def add(self, item: Item) -> Item:
        tokenized = item.with_tokens(tokenize(item.searchable_text()))
        self._items[tokenized.id] = tokenized
        self._index.add(tokenized.id, tokenized.tokens)
        for term in tokenized.tokens:
            self._trie.insert(term)
        self._by_date.insert(tokenized.id, tokenized.date_iso)
        return tokenized

    def remove(self, item_id: int) -> dict[str, int]:
        item = self._items.pop(item_id, None)
        if item is None:
            raise KeyError(item_id)
        postings_scanned = self._index.remove(item.id, item.tokens)
        for term in item.tokens:
            self._trie.remove(term)
        ids_shifted = self._by_date.remove(item.id, item.date_iso)
        return {"postings_scanned": postings_scanned, "ids_shifted": ids_shifted}

    def replace(self, item: Item) -> Item:
        """An edit is delete-then-insert in the index: the honest cost."""
        if item.id in self._items:
            self.remove(item.id)
        return self.add(item)

    def get(self, item_id: int) -> Item | None:
        return self._items.get(item_id)

    # -- reads -----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._items)

    def all_items(self) -> list[Item]:
        return list(self._items.values())

    def newest(self, limit: int | None = None) -> list[Item]:
        ids = self._by_date.newest_first()
        if limit is not None:
            ids = ids[:limit]
        return [self._items[item_id] for item_id in ids if item_id in self._items]

    @property
    def index_stats(self) -> dict:
        return {
            "documents": len(self._items),
            "terms": self._index.term_count,
            "postings": self._index.posting_count,
            "trie_nodes": self._trie.node_count,
            "build_ms": round(self.build_ms, 4),
        }

    def suggestions(self, prefix: str, limit: int = 8) -> list[dict]:
        walk = self._trie.complete(prefix.lower(), limit)
        return [
            {"term": term, "df": self._index.document_frequency(term)}
            for term in walk.terms
        ]

    # -- the two paths ---------------------------------------------------
    def _indexed_ids(self, query_tokens: tuple[str, ...]) -> tuple[set[int], dict[str, int]]:
        diagnostics = {"trie_nodes_visited": 0, "terms_enumerated": 0, "postings_read": 0}
        per_token: list[set[int]] = []
        for token in query_tokens:
            walk = self._trie.walk(token)
            diagnostics["trie_nodes_visited"] += walk.nodes_visited
            diagnostics["terms_enumerated"] += len(walk.terms)
            candidates: set[int] = set()
            for term in walk.terms:
                postings = self._index.postings(term)
                diagnostics["postings_read"] += len(postings)
                candidates.update(postings)
            per_token.append(candidates)
        if not per_token:
            return set(), diagnostics
        result = per_token[0]
        for other in per_token[1:]:
            result &= other
        return result, diagnostics

    def _linear_ids(self, query_tokens: tuple[str, ...]) -> tuple[set[int], dict[str, int]]:
        diagnostics = {"prefix_tests": 0, "items_short_circuited": 0}
        matched: set[int] = set()
        for item_id, item in self._items.items():
            item_matches = True
            for token in query_tokens:
                hit = False
                for candidate in item.tokens:
                    diagnostics["prefix_tests"] += 1
                    if candidate.startswith(token):
                        hit = True
                        break
                if not hit:
                    item_matches = False
                    diagnostics["items_short_circuited"] += 1
                    break
            if item_matches:
                matched.add(item_id)
        return matched, diagnostics

    def _measure(self, run: Callable[[], tuple[set[int], dict[str, int]]], runs: int):
        run()  # warm-up, untimed
        durations: list[float] = []
        last_ids: set[int] = set()
        last_diagnostics: dict[str, int] = {}
        for _ in range(max(1, runs)):
            started = time.perf_counter()
            last_ids, last_diagnostics = run()
            durations.append((time.perf_counter() - started) * 1000.0)
        return last_ids, statistics.median(durations), last_diagnostics

    def _allowed_ids(self, filters: Filters) -> set[int] | None:
        allowed: set[int] | None = None
        if filters.date_from or filters.date_to:
            allowed = set(self._by_date.between(filters.date_from, filters.date_to))
        if filters.category:
            wanted = filters.category.strip().lower()
            subset = {i for i, item in self._items.items() if item.category.lower() == wanted}
            allowed = subset if allowed is None else allowed & subset
        if filters.status:
            wanted = filters.status.strip().lower()
            subset = {i for i, item in self._items.items() if item.status.lower() == wanted}
            allowed = subset if allowed is None else allowed & subset
        return allowed

    @staticmethod
    def _matched_counts(items: Iterable[Item], query_tokens: tuple[str, ...]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for item in items:
            hits = 0
            for token in query_tokens:
                if any(candidate.startswith(token) for candidate in item.tokens):
                    hits += 1
            counts[item.id] = hits
        return counts

    def _browse(self, filters: Filters) -> SearchResult:
        allowed = self._allowed_ids(filters)
        ids = self._by_date.newest_first()
        if allowed is not None:
            ids = [item_id for item_id in ids if item_id in allowed]
        items = [self._items[item_id] for item_id in ids if item_id in self._items]
        return SearchResult(
            query="",
            tokens=(),
            mode="browse",
            ids=ids,
            items=items,
            indexed=None,
            linear=None,
            equal=None,
            only_indexed=[],
            only_linear=[],
            corpus_size=len(self._items),
            index_stats=self.index_stats,
            note="no query tokens: showing browse order, not search results",
        )

    def search(
        self,
        query: str,
        filters: Filters | None = None,
        timing_runs: int = TIMING_RUNS,
    ) -> SearchResult:
        filters = filters or Filters()
        query_tokens = tuple(tokenize(query))
        if not query_tokens:
            return self._browse(filters)

        indexed_ids, indexed_ms, indexed_diag = self._measure(
            lambda: self._indexed_ids(query_tokens), timing_runs
        )
        linear_ids, linear_ms, linear_diag = self._measure(
            lambda: self._linear_ids(query_tokens), timing_runs
        )

        allowed = self._allowed_ids(filters)
        final_indexed = indexed_ids if allowed is None else indexed_ids & allowed
        final_linear = linear_ids if allowed is None else linear_ids & allowed
        equal = final_indexed == final_linear
        only_indexed = sorted(final_indexed - final_linear)
        only_linear = sorted(final_linear - final_indexed)

        candidates = [self._items[item_id] for item_id in final_indexed if item_id in self._items]
        counts = self._matched_counts(candidates, query_tokens)
        ranked, sort_stats = sort_ranked(candidates, counts)

        indexed_metrics = PathMetrics(
            items_examined=len(indexed_ids),
            compute_ms=indexed_ms,
            diagnostics=indexed_diag,
        )
        linear_metrics = PathMetrics(
            items_examined=len(self._items),
            compute_ms=linear_ms,
            diagnostics=linear_diag,
        )

        return SearchResult(
            query=query,
            tokens=query_tokens,
            mode="search",
            ids=[item.id for item in ranked],
            items=ranked,
            indexed=indexed_metrics,
            linear=linear_metrics,
            equal=equal,
            only_indexed=only_indexed,
            only_linear=only_linear,
            corpus_size=len(self._items),
            index_stats=self.index_stats,
            sort=sort_stats,
        )

    # -- the audit the panel can re-run by hand --------------------------
    def audit_queries(self, limit: int = 50) -> list[str]:
        terms = sorted(
            self._index.terms(),
            key=lambda term: (-self._index.document_frequency(term), term),
        )
        queries: list[str] = []

        def add(value: str) -> None:
            value = value.strip()
            if value and value not in queries:
                queries.append(value)

        for term in terms[:14]:
            add(term)
        for term in terms[:5]:
            for size in (2, 3, 4):
                add(term[:size])
        for index in range(0, min(8, len(terms) - 1), 2):
            add(f"{terms[index]} {terms[index + 1]}")
        if "carved" in self._index:
            add("carved handle")
        for term in terms[-4:]:
            add(term)
        add("zzzznotathing")  # zero matches on both paths
        for item in self.newest(5):
            add(item.title)
        for term in terms[14:]:
            if len(queries) >= limit + 10:
                break
            add(term)

        # Only queries that produce tokens go through both paths; the two
        # browse cases are appended after the comparable ones so the audit
        # really compares `limit` queries rather than 50 minus its own edges.
        comparable = [query for query in queries if tokenize(query)]
        return comparable[:limit] + [
            "sa ng mga",  # stopwords only -> browse, no speed claim
            "p",  # one character -> tokenizes to nothing -> browse
        ]

    def audit(self, limit: int = 50) -> AuditReport:
        queries = self.audit_queries(limit)
        mismatches: list[dict] = []
        compared = 0
        for query in queries:
            result = self.search(query, timing_runs=3)
            if result.mode != "search" or result.equal is None:
                continue
            compared += 1
            if not result.equal:
                mismatches.append(
                    {
                        "query": query,
                        "tokens": list(result.tokens),
                        "only_indexed": result.only_indexed,
                        "only_linear": result.only_linear,
                    }
                )
        return AuditReport(
            queries=len(queries),
            compared=compared,
            mismatches=mismatches,
            corpus_size=len(self._items),
            index_stats=self.index_stats,
        )
