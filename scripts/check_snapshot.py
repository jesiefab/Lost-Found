#!/usr/bin/env python3
"""Fail if the committed snapshot no longer matches the generator.

    python scripts/check_snapshot.py

Compares the row count, the sha256 and every row. Exit status 1 means the
snapshot is stale: regenerate it with `python scripts/seed.py --emit-snapshot`
and look at what changed, because the panel's numbers describe these rows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from seed import SNAPSHOT_PATH, build_rows, snapshot_sha256  # noqa: E402


def main() -> int:
    if not SNAPSHOT_PATH.exists():
        print("missing %s — run python scripts/seed.py --emit-snapshot" % SNAPSHOT_PATH)
        return 1

    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    rows = build_rows()
    problems: list[str] = []

    if payload.get("count") != len(rows):
        problems.append("count: snapshot %r, generator %d" % (payload.get("count"), len(rows)))
    digest = snapshot_sha256(rows)
    if payload.get("sha256") != digest:
        problems.append("sha256: snapshot %s, generator %s" % (payload.get("sha256"), digest))

    committed = payload.get("rows") or []
    if len(committed) != len(rows):
        problems.append("rows: snapshot %d, generator %d" % (len(committed), len(rows)))
    differences = 0
    for index, (left, right) in enumerate(zip(committed, rows)):
        if left != right:
            differences += 1
            if differences <= 5:
                changed = sorted(
                    key for key in set(left) | set(right) if left.get(key) != right.get(key)
                )
                problems.append(
                    "row %d (id %r) differs in %s" % (index + 1, right.get("id"), ", ".join(changed))
                )
    if differences > 5:
        problems.append("... %d rows differ in total" % differences)

    if problems:
        print("snapshot is STALE:")
        for problem in problems:
            print("  - %s" % problem)
        return 1

    print(
        "snapshot OK: %d rows, sha256 %s, seed %s"
        % (len(rows), digest[:16], payload.get("seed_version"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
