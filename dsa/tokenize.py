"""The one tokenizer, used by the corpus, the query and both paths.

Lowercase, split on anything that is not a letter or digit, drop stopwords and
tokens shorter than 2 characters, de-duplicate while keeping order. `[^\\W_]+`
keeps accented letters ("baño"), so Filipino spelling survives.
"""

from __future__ import annotations

import re

MIN_TOKEN_LEN = 2
MIN_QUERY_CHARS = 2  # the API rejects a raw query shorter than this

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of in on at to from
    by for with without about over under into out up down is are was were be
    been being am do does did done have has had having i you he she it we they
    me him her us them my your his its our their mine yours theirs who whom
    whose which what when where why how not no nor so too very just also only
    again still as all any some each every few more most other such own same
    there here now
    ang mga ng nang sa na si sina ni nina kay kina ko mo niya namin natin ninyo
    nila ako ikaw siya kami tayo kayo sila ito iyan iyon yung yun lang din rin
    daw raw naman kasi pero tapos ba po opo oo hindi hinde para
    """.split()
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _keep(token: str) -> bool:
    return len(token) >= MIN_TOKEN_LEN and token not in STOPWORDS


def tokenize(text: str | None) -> list[str]:
    """Unique tokens in first-seen order. Same function for rows and queries."""
    if not text:
        return []
    found: dict[str, None] = {}
    for raw in _WORD.findall(text.lower()):
        if _keep(raw):
            found.setdefault(raw, None)
    return list(found)


def tokenize_all(text: str | None) -> list[str]:
    """Every occurrence, duplicates included. Only the seed audit uses this."""
    if not text:
        return []
    return [raw for raw in _WORD.findall(text.lower()) if _keep(raw)]
