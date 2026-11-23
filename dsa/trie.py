"""Prefix trie over the vocabulary, each terminal carrying a document frequency.

Load-bearing for the matching rule: walking to the node for a prefix enumerates
*exactly* the terms that start with it, which is how the indexed path answers
the same question the linear scan answers with `str.startswith`.
"""

from __future__ import annotations

from dataclasses import dataclass


class _Node:
    __slots__ = ("children", "term", "df")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.term: str | None = None
        self.df = 0


@dataclass(frozen=True)
class PrefixWalk:
    """The terms under a prefix, plus how much of the trie was touched."""

    terms: tuple[str, ...]
    nodes_visited: int

    def __bool__(self) -> bool:
        return bool(self.terms)


class Trie:
    def __init__(self) -> None:
        self._root = _Node()

    # -- writes ---------------------------------------------------------
    def insert(self, term: str, df: int = 1) -> None:
        node = self._root
        for char in term:
            node = node.children.setdefault(char, _Node())
        if node.term is None:
            node.term = term
            node.df = df
        else:
            node.df += df

    def remove(self, term: str) -> None:
        """Decrement the term's document frequency and prune dead branches."""
        path: list[tuple[_Node, str]] = []
        node = self._root
        for char in term:
            child = node.children.get(char)
            if child is None:
                return
            path.append((node, char))
            node = child
        if node.term is None:
            return
        node.df -= 1
        if node.df > 0:
            return
        node.term = None
        for parent, char in reversed(path):
            child = parent.children.get(char)
            if child is None:
                break
            if child.term is None and not child.children:
                del parent.children[char]
            else:
                break

    # -- reads ----------------------------------------------------------
    def walk(self, prefix: str) -> PrefixWalk:
        """Every term starting with `prefix`, and the nodes visited to get there."""
        node = self._root
        visited = 0
        for char in prefix:
            child = node.children.get(char)
            visited += 1
            if child is None:
                return PrefixWalk((), visited)
            node = child

        terms: list[str] = []
        stack = [node]
        while stack:
            current = stack.pop()
            visited += 1
            if current.term is not None:
                terms.append(current.term)
            for char in sorted(current.children, reverse=True):
                stack.append(current.children[char])
        return PrefixWalk(tuple(terms), visited)

    def complete(self, prefix: str, limit: int = 8) -> PrefixWalk:
        """Autocomplete: terms under `prefix`, most-used first."""
        found = self.walk(prefix)
        if not found.terms:
            return found
        ordered = sorted(found.terms, key=lambda term: (-self.df(term), term))
        return PrefixWalk(tuple(ordered[:limit]), found.nodes_visited)

    def df(self, term: str) -> int:
        node = self._root
        for char in term:
            node = node.children.get(char)
            if node is None:
                return 0
        return node.df

    @property
    def node_count(self) -> int:
        total = 0
        stack = [self._root]
        while stack:
            node = stack.pop()
            total += 1
            stack.extend(node.children.values())
        return total
