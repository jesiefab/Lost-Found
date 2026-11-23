#!/usr/bin/env python3
"""Deterministic seed: 500 deliberately messy lost & found rows.

One source of truth for both stores:

    python scripts/seed.py --report            # measure the corpus
    python scripts/seed.py --emit-snapshot     # write data/snapshot.json
    python scripts/seed.py --push              # insert into Supabase (needs env)

`--emit-snapshot` and `--push` write the same rows including ids, so the
offline demo and the deployed board answer the same queries identically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SNAPSHOT_PATH = ROOT / "data" / "snapshot.json"
SEED = 20261123
SEED_VERSION = "lost-found-seed-v1"
TOTAL = 500
FIRST_DAY = date(2026, 8, 1)
LAST_DAY = date(2026, 11, 22)

LOCATIONS = [
    "covered court, bench 3", "covered court, bench 7", "gym lobby",
    "gym bleachers", "gym stage", "canteen table 12", "canteen counter",
    "canteen line", "canteen sink", "library 2nd floor", "library reading area",
    "silent area", "group study room", "study hall", "thesis room",
    "room 105", "room 204", "room 210", "room 302", "room 311", "room 415",
    "lab 1", "lab 3", "computer lab 2", "science lab", "avr",
    "faculty room", "faculty lounge", "registrar window", "cashier window",
    "bookstore", "printing shop", "guard house", "guard station",
    "main gate", "back gate", "side gate", "bike rack", "motor shed",
    "chapel", "chapel entrance", "auditorium", "student lounge",
    "org room", "basketball court", "volleyball court", "tennis court",
    "track oval", "field bleachers", "stage left", "stage right",
    "locker room", "comfort room 2nd floor", "stairs near room 105",
    "fire exit", "waiting shed", "beside the water dispenser",
    "front of the clinic", "clinic waiting area", "jeepney stop",
    "jeepney terminal", "tricycle stop", "covered walk", "quadrangle",
    "field", "bleachers near the stage", "walkway near gate", "footbridge",
    "garden", "flagpole", "admin building", "annex building", "old building",
    "new building", "fourth floor hallway", "third floor lobby",
    "second floor stairs", "elevator lobby", "bench sa may gate",
    "sakayan ng jeep",
]

REPORTERS = [
    "mika", "jomar", "bea", "kuya ron", "ate shai", "kim", "jessa", "paolo",
    "trisha", "mark", "andrea", "carlo", "nicole", "jr", "ella", "dave",
    "rish", "karlo", "mai", "jp", "chesca", "bryan", "joy", "adrian",
    "camille", "renzo", "abby", "gelo", "tintin", "migs", "sasa", "nico",
    "lala", "bong", "che", "denden", "franco", "gigi", "hazel", "ivan",
]

ADJECTIVES = [
    "itim", "black", "asul", "blue", "pula", "red", "puti", "white", "gray",
    "grey", "berde", "green", "rosas", "pink", "kayumanggi", "brown",
    "dilaw", "yellow", "lila", "violet", "orange", "cream", "silver", "gold",
    "maliit", "malaki", "luma", "bago", "manipis", "makapal", "transparent",
    "plain", "malambot", "matigas", "plastik", "leather", "canvas", "denim",
    "metal", "kahoy", "wooden", "may design", "may logo", "may butas",
    "may bulsa", "sirang", "gumagana", "basag", "buo", "mamahalin", "mura",
    "mabigat", "magaan", "second hand", "ukay", "faded",
]

TAGS = [
    "urgent", "may reward", "found", "lost", "school", "gym", "canteen",
    "library", "asap", "salamat", "checked", "unclaimed", "ngalan", "resibo",
    "susi", "barya", "charger", "earphones", "wallet", "pitaka", "notebook",
    "folder", "jacket", "tumbler", "calculator", "rosary", "ID", "lanyard",
    "asul", "itim", "pula", "puti", "bag", "payong", "cellphone",
    "second hand", "ukay", "PE", "exam week", "rush",
]

DETAILS = [
    "may maliit na butas", "may sticker ng pusa", "may keychain na maliit",
    "medyo luma na", "bago pa", "may ngalan sa loob", "may laso na pula",
    "may sira sa zipper", "walang laman", "may lamang ballpen",
    "may buhangin", "amoy bagong bili", "may tag na presyo pa",
    "kulang ang isang strap", "may mantsa", "makinis pa", "gumagana pa",
    "basag ang screen", "may crack sa gilid", "may eraser sa dulo",
    "may papel sa loob", "may resibo", "may susi", "may coin purse",
    "may jacket sa loob", "mabigat", "magaan lang", "may lasa ng kape",
    "may initials sa loob", "may piraso ng chalk", "may nota sa likod",
    "may drawing ng bituin", "may tape na asul", "may bulsa sa loob",
    "kulay faded na", "may amoy sabon", "may buhok ng pusa", "may barya sa loob",
    "may ID picture sa loob", "may strap na mahaba", "may logo ng school",
    "may numero sa likod", "may marka ng pentel pen", "may tape sa gilid",
    "may butas sa sulok", "may ribbon na dilaw", "may laman na papel",
    "may sticker ng bituin", "may sulat sa likod", "may drawing ng puso",
    "may tinta sa gilid", "may lamang notebook", "may lamang libro",
    "may lamang charger", "may lamang susi", "may lamang barya",
    "may lamang candy", "may lamang ID", "may lamang tumbler",
    "may lamang calculator", "may lamang rosary", "may lamang earphones",
    "may lamang sim card", "may lamang memory card", "may lamang flash drive",
    "may lamang panyo", "may lamang panyo at papel", "may lamang jacket",
    "may lamang libro at notebook", "may lamang wallet", "may lasa ng kendi",
]

CONTEXTS = [
    "kanina lang mga 3pm", "kahapon lunch time", "after PE class",
    "during the intramurals", "habang naglalakad sa walkway",
    "after ng exam", "nung flag ceremony", "sa jeep pauwi",
    "before mag-uwian", "nung nagkita kami sa canteen", "last friday",
    "kaninang umaga", "before lunch", "after ng class sa room 204",
    "nung naglalaro kami sa court", "habang naghihintay ng jeep",
    "nung break time", "after ng org meeting", "sa may flagpole",
    "nung uwian na", "habang nag-aaral sa library", "during the film showing",
    "nung may practice kami sa stage", "kanina bago magsimula ang klase",
    "last week lang", "nung field trip", "sa loob ng jeepney",
    "habang umuulan", "nung nakaupo kami sa bench", "after ng quiz",
]

NOUNS = {
    "umbrella": ["payong", "umbrella", "payonggg", "payung", "folding umbrella",
                 "payong na folding", "payong na maliit", "payong na malaki",
                 "payong na automatic", "payong na manual", "payong na may case",
                 "payong na itim", "payong na asul", "payong na pula",
                 "payong na puti", "payong na bago", "payong na luma",
                 "matic na payong", "umbrella na folding"],
    "phone": ["cellphone", "celfone", "phone", "cellfone", "android phone",
              "iphone", "smartphone", "cellphone na lumang model",
              "cellphone na may case", "cellphone na basag", "cellphone na itim",
              "cellphone na asul", "tablet", "powerbank", "headphones",
              "earphones", "charger", "charging cable", "phone case", "sim card"],
    "id": ["student ID", "ID", "school ID", "lanyard ID", "ID card",
           "school ID na may lanyard", "ID na may picture", "library card",
           "ATM card", "discount ID", "alumni ID", "visitor pass", "ID lace",
           "ID holder", "ID strap", "RFID card", "school ID na bago",
           "school ID na luma"],
    "bag": ["bag", "tote bag", "backpack", "shoulder bag", "pouch",
            "sling bag", "eco bag", "gym bag", "laptop bag", "makeup pouch",
            "paper bag", "plastic bag", "bayong", "handbag", "travel bag",
            "drawstring bag", "cooler bag", "pencil case"],
    "paper": ["papel", "papeles", "notebook", "folder", "bond paper",
              "assignment", "test paper", "index card", "quiz paper",
              "reviewer", "handouts", "manila paper", "cartolina",
              "worksheet", "certificate", "receipt", "envelope",
              "folder na asul"],
    "other": ["pitaka", "wallet", "coin purse", "keychain", "ballpen",
              "pencil", "ruler", "jacket", "hoodie", "tumbler",
              "water bottle", "calculator", "rosary", "cap", "ball cap",
              "socks", "PE uniform", "ID picture", "memory card", "flash drive",
              "USB", "watch", "bracelet", "ring", "necklace", "glasses",
              "shades", "umbrella case"],
}

CATEGORY_WEIGHTS = {
    "umbrella": 22, "phone": 18, "id": 16, "bag": 14, "paper": 12, "other": 18,
}

# Surfaces that make the low-selectivity `pa` case real. Never a tokenizer
# stopword, never shorter than 2 characters.
PA_PHRASES = [
    "paki check na lang", "pasuyo naman mga mare", "pahingi update kung meron",
    "pakiusap, importante sa akin ito", "papel na may pangalan sa loob",
    "pasok sa office bukas", "panyo lang pero bigay ng lola ko",
    "pantalon din pala nawala ko", "panlib ko yun", "paypay na kulay asul",
    "pakibigay na lang sa guard", "paleta ko rin nawala",
]

LOST_PHRASES = [
    "nawala ko {noun} ko mga mare, naiwan ata sa {loc}, {detail}",
    "i lost my {noun} somewhere near {loc} huhu, {detail}",
    "nawala {noun} ko!!! baka may nakakita, {loc} ako kanina",
    "pa help naman mga mare, missing {noun} ko since kanina, {loc}",
    "{noun} ko nawala, {detail}, huling hawak ko sa {loc}",
    "sino nakakita ng {noun} ko? {detail}, {loc} ako kanina",
]

FOUND_PHRASES = [
    "nakita ko {noun} sa {loc}, {detail}, sino may-ari?",
    "found {noun} near {loc}, {detail}, dm me",
    "may naiwan na {noun} sa {loc} mga mare, {detail}",
    "nahanap {noun} sa {loc} kanina lang, {detail}!!!",
    "sino nawalan ng {noun}? nasa {loc}, {detail}, tanong lang sa guard",
]

# Five clusters: the same object described differently, different ids,
# locations and dates within a few days. Ranking has to earn its answer.
CLUSTERS = [
    {
        "category": "umbrella",
        "variants": [
            {"kind": "lost", "title": "Black folding umbrella",
             "description": "nawala payong ko mga mare, black folding, naiwan sa gym kanina"},
            {"kind": "lost", "title": "payong itim na folding",
             "description": "black payong, nawala sa gym lobby, may strap na maliit"},
            {"kind": "found", "title": "Umbrella, itim",
             "description": "found umbrella near gym bleachers, black, may strap"},
            {"kind": "lost", "title": "itim na payong na folding",
             "description": "nawala ko payong ko, itim, folding, sa gym mga mare"},
        ],
    },
    {
        "category": "phone",
        "variants": [
            {"kind": "lost", "title": "Blue cellphone, cracked screen",
             "description": "nawala cellphone ko, blue case, basag ang screen sa gilid"},
            {"kind": "lost", "title": "celfone asul",
             "description": "lost phone, asul na case, may crack sa screen"},
            {"kind": "found", "title": "cellphone na may blue case",
             "description": "found blue cellphone near canteen, basag screen"},
        ],
    },
    {
        "category": "id",
        "variants": [
            {"kind": "lost", "title": "Student ID, blue lanyard",
             "description": "nawala student ID ko, asul na lanyard, 2nd year"},
            {"kind": "lost", "title": "ID ko nawala, asul na lanyard",
             "description": "nawala ID ko mga mare, blue lanyard, may picture"},
            {"kind": "found", "title": "school ID na may blue lanyard",
             "description": "found school ID sa library, blue lanyard, 2nd year"},
            {"kind": "found", "title": "ID card, 2nd year",
             "description": "may naiwan na ID card sa library 2nd floor, asul na lanyard"},
            {"kind": "lost", "title": "lanyard ID, blue",
             "description": "nawala lanyard ID ko, blue, 2nd year, may picture"},
        ],
    },
    {
        "category": "bag",
        "variants": [
            {"kind": "lost", "title": "Brown tote bag, may notebook",
             "description": "nawala bag ko, brown tote, may notebook sa loob"},
            {"kind": "lost", "title": "tote bag kayumanggi, may notebook",
             "description": "brown tote bag ko nawala, may notebook at ballpen sa loob"},
            {"kind": "found", "title": "bag ko, brown tote, notebook at ballpen",
             "description": "found brown tote bag sa canteen, may notebook at ballpen"},
        ],
    },
    {
        "category": "other",
        "variants": [
            {"kind": "lost", "title": "Small brown coin purse",
             "description": "nawala coin purse ko, maliit, brown, may barya"},
            {"kind": "lost", "title": "pitaka na maliit, may barya",
             "description": "nawala pitaka ko, maliit, brown, may barya at susi"},
            {"kind": "found", "title": "coin purse, maliit, brown, may susi",
             "description": "found small wallet sa sakayan ng jeep, brown, may susi"},
            {"kind": "found", "title": "small wallet, may coins at susi",
             "description": "may naiwan na small wallet sa jeepney stop, may barya at susi"},
        ],
    },
]

# Exactly two items mention both reserved stems, so `carved handle` is the
# high-selectivity chip: two matches, not a cluster of near-duplicates.
CARVED = [
    {"kind": "found", "category": "umbrella",
     "title": "Black umbrella, carved wooden handle",
     "description": "found near the covered court, carved handle, may initials sa loob",
     "location": "covered court, bench 7"},
    {"kind": "lost", "category": "umbrella",
     "title": "payong itim na may carved handle",
     "description": "nawala payong ko mga mare, carved wooden handle, naiwan sa gym lobby",
     "location": "gym lobby"},
]

NOISE_TAILS = ["!!!", "...", "😭", "🙏", "asap!!", "huhu", "mga mare pls"]


def _day(rng: random.Random) -> date:
    return FIRST_DAY + timedelta(days=rng.randrange(0, (LAST_DAY - FIRST_DAY).days + 1))


def _row(item_id: int, *, kind: str, category: str, title: str, description: str,
         location: str, day: date, rng: random.Random) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "location": location,
        "date_iso": day.isoformat(),
        "status": rng.choices(["open", "claimed", "returned"], weights=[62, 23, 15])[0],
        "reporter": rng.choice(REPORTERS),
        "tags": rng.sample(TAGS, k=rng.choice([0, 0, 1, 1, 2, 3])),
        "is_sample": True,
        "owner_token": f"sample-{item_id:03d}",
    }


def _messy(text: str, noun: str, rng: random.Random) -> str:
    """Group-chat noise: stretched letters, casing drift, emoji, punctuation."""
    if rng.random() < 0.12 and noun in text:
        text = text.replace(noun, noun + "gg", 1)
    if rng.random() < 0.10:
        text = text.replace(noun, noun.upper(), 1) if noun in text else text
    if rng.random() < 0.22:
        text = f"{text} {rng.choice(NOISE_TAILS)}"
    return text


def _maybe_pa(text: str, rng: random.Random) -> str:
    """Roughly a third of random items pick up a `pa…` phrase."""
    if rng.random() < 0.12:
        return f"{text}, {rng.choice(PA_PHRASES)}"
    return text


def _maybe_repeat(text: str, rng: random.Random) -> str:
    """35% of items repeat a token, which exercises the unique-token rule."""
    if rng.random() >= 0.35:
        return text
    words = [word.strip(",.!?") for word in text.split()]
    candidates = [word for word in words if len(word) >= 4 and word.isalpha()]
    if not candidates:
        return text
    token = rng.choice(candidates)
    return f"{text} | {token}... {token} talaga"


def _random_row(item_id: int, rng: random.Random) -> dict:
    categories = list(CATEGORY_WEIGHTS)
    category = rng.choices(categories, weights=[CATEGORY_WEIGHTS[c] for c in categories])[0]
    noun = rng.choice(NOUNS[category])
    kind = "lost" if rng.random() < 0.5 else "found"
    adjective = rng.choice(ADJECTIVES)
    location = rng.choice(LOCATIONS)
    title = rng.choice([
        f"{adjective.capitalize()} {noun}",
        f"{noun.capitalize()} — {adjective}",
        f"{noun} ko mga mare",
        f"{adjective} na {noun}",
        f"{noun}, {location.split(',')[0]}",
    ])
    phrasing = rng.choice(LOST_PHRASES if kind == "lost" else FOUND_PHRASES)
    description = phrasing.format(
        noun=noun, loc=location, detail=rng.choice(DETAILS), color=adjective
    )
    if rng.random() < 0.55:
        description = f"{description}, {rng.choice(CONTEXTS)}"
    description = _messy(description, noun, rng)
    description = _maybe_pa(description, rng)
    description = _maybe_repeat(description, rng)
    return _row(
        item_id,
        kind=kind,
        category=category,
        title=title,
        description=description,
        location=location,
        day=_day(rng),
        rng=rng,
    )


def build_rows(total: int = TOTAL, seed: int = SEED) -> list[dict]:
    """The 500 rows. Same seed, same bytes, every run."""
    rng = random.Random(seed)
    rows: list[dict] = []
    next_id = 1

    for cluster in CLUSTERS:
        start = _day(rng)
        for offset, variant in enumerate(cluster["variants"]):
            rows.append(
                _row(
                    next_id,
                    kind=variant["kind"],
                    category=cluster["category"],
                    title=variant["title"],
                    description=variant["description"],
                    location=LOCATIONS[(next_id * 7) % len(LOCATIONS)],
                    day=start + timedelta(days=offset % 4),
                    rng=rng,
                )
            )
            next_id += 1

    for carved in CARVED:
        rows.append(
            _row(
                next_id,
                kind=carved["kind"],
                category=carved["category"],
                title=carved["title"],
                description=carved["description"],
                location=carved["location"],
                day=_day(rng),
                rng=rng,
            )
        )
        next_id += 1

    while next_id <= total:
        rows.append(_random_row(next_id, rng))
        next_id += 1

    return rows


def snapshot_sha256(rows: list[dict]) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_payload(rows: list[dict]) -> dict:
    return {
        "seed_version": SEED_VERSION,
        "generator": "scripts/seed.py",
        "seed": SEED,
        "count": len(rows),
        "sha256": snapshot_sha256(rows),
        "rows": rows,
    }


def emit_snapshot(rows: list[dict]) -> Path:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(build_payload(rows), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return SNAPSHOT_PATH


def report(rows: list[dict]) -> None:
    """Measure the corpus with the real tokenizer and the real search engine."""
    from dsa import Item, SearchEngine, tokenize, tokenize_all

    items = [Item.from_row(row) for row in rows]
    engine = SearchEngine(items)

    vocab: set[str] = set()
    twice = 0
    thrice = 0
    token_total = 0
    raw_total = 0
    longest = 0
    for item in engine.all_items():
        vocab.update(item.tokens)
        token_total += len(item.tokens)
        longest = max(longest, len(item.tokens))
        raw = tokenize_all(item.searchable_text())
        raw_total += len(raw)
        counts: dict[str, int] = {}
        for token in raw:
            counts[token] = counts.get(token, 0) + 1
        peak = max(counts.values()) if counts else 0
        if peak >= 2:
            twice += 1
        if peak >= 3:
            thrice += 1

    pa_terms = sorted(term for term in vocab if term.startswith("pa"))
    pa_items = [item for item in engine.all_items() if any(t.startswith("pa") for t in item.tokens)]
    carved = engine.search("carved handle", timing_runs=3)
    worst = engine.search("pa", timing_runs=3)
    best = carved
    audit = engine.audit()

    print()
    print("seed report — %s (seed %d)" % (SEED_VERSION, SEED))
    print("  rows                     %d" % len(rows))
    print("  distinct terms           %d" % len(vocab))
    print("  tokens per item          mean %.1f unique, max %d (%d raw slots, %.0f%% deduped)" % (
        token_total / max(1, len(items)), longest, raw_total,
        100.0 * (raw_total - token_total) / max(1, raw_total)))
    print("  items with a repeat      %d (%.0f%%) twice, %d (%.0f%%) three or more" % (
        twice, 100.0 * twice / max(1, len(items)),
        thrice, 100.0 * thrice / max(1, len(items))))
    print("  items with a `pa…` term  %d (%.0f%%), %d distinct pa terms" % (
        len(pa_items), 100.0 * len(pa_items) / max(1, len(items)), len(pa_terms)))
    print("    %s" % ", ".join(pa_terms[:18]))
    print("  near-duplicate clusters  %d" % len(CLUSTERS))
    print("  `carved handle`          %d match(es)" % len(best.ids))
    print("  `pa` worst case          indexed %d vs linear %d items examined (%.1fx)" % (
        worst.indexed.items_examined, worst.linear.items_examined, worst.ratio_items or 0.0))
    print("  index                    %d terms, %d postings, %d trie nodes, build %.1f ms" % (
        engine.index_stats["terms"], engine.index_stats["postings"],
        engine.index_stats["trie_nodes"], engine.index_stats["build_ms"]))
    print("  audit                    %d queries, %d compared, %d mismatches" % (
        audit.queries, audit.compared, len(audit.mismatches)))
    top = sorted(vocab, key=lambda term: -engine._index.document_frequency(term))[:10]
    print("  top terms                %s" % ", ".join(
        "%s (%d)" % (term, engine._index.document_frequency(term)) for term in top))
    print()


def push(rows: list[dict]) -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to push.", file=sys.stderr)
        return 2
    try:
        from supabase import create_client
    except ImportError:
        print("supabase-py is not installed: pip install -r requirements.txt", file=sys.stderr)
        return 2

    client = create_client(url, key)
    table = client.table("items")
    existing = table.select("id", count="exact").eq("is_sample", True).execute()
    if (existing.count or 0) == len(rows):
        print("sample rows already present (%d) — nothing to do." % existing.count)
    else:
        if existing.count:
            print("removing %d existing sample rows..." % existing.count)
            table.delete().eq("is_sample", True).execute()
        for start in range(0, len(rows), 100):
            chunk = rows[start:start + 100]
            table.insert(chunk).execute()
            print("  inserted %d/%d" % (min(start + 100, len(rows)), len(rows)))

    print()
    print("Move the sequence past the seed, once, in the Supabase SQL editor:")
    print("  select setval(pg_get_serial_sequence('items', 'id'), (select max(id) from items));")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the lost & found board.")
    parser.add_argument("--emit-snapshot", action="store_true",
                        help="write data/snapshot.json (committed)")
    parser.add_argument("--push", action="store_true",
                        help="insert the same rows into Supabase")
    parser.add_argument("--report", action="store_true", help="print corpus measurements")
    args = parser.parse_args(argv)

    if not (args.emit_snapshot or args.push or args.report):
        parser.print_help()
        return 1

    rows = build_rows()
    if args.report:
        report(rows)
    if args.emit_snapshot:
        path = emit_snapshot(rows)
        print("wrote %s (%d rows, sha256 %s)" % (
            path.relative_to(ROOT), len(rows), snapshot_sha256(rows)))
    if args.push:
        return push(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
