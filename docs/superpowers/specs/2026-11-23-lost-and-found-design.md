# Lost & Found Board with a Real Search Index — Design

- Date: 2026-11-23
- Course: CCC121 (data structures & algorithms project)
- Stack: Python 3.12 + Flask on Vercel, Supabase Postgres, Tailwind CSS
- Status: proposed, awaiting approval

## Intent and why

The problem is not "build a lost & found page." It is: **a board with 500 items is unusable without search, and search without an index is a linear scan.** The project exists to make that second half visible — the same query answered twice, once with an inverted index and once by scanning everything, with the work counted on screen.

That is also why it was chosen over the alternatives. The rubric asks for one data structure and one search or sort algorithm doing real work. In most student apps those are decorative: an array would have done, and the tree is bolted on for the grade. Here the index is the product. Remove it and the feature is slower and visibly worse, which is the whole defense.

Who benefits, honestly: a class, org, or household group chat where "may nakakita ng payong?" is asked 200 messages too late. The friction is real but it is *community* friction, not personal daily friction. That trade was accepted because the grade — not adoption — is what this project is for.

## Goals

- Every rubric bullet observable in one screen, without opening a console.
- One query, two implementations of the *same* matching rule: indexed and linear, side by side, compared on items examined and median compute time.
- A structure that cannot be faked: writing an item must cost something the panel can see, because that cost is what buying fast lookups costs you.
- **A public URL on Vercel**: the Flask app deployed as a Python function, reachable from a link in the submission, working when the laptop is closed.
- **One shared board**: an item posted from a phone appears on the laptop, because items live in Supabase Postgres rather than in one browser.
- **A demo the room cannot break**: with the wifi off and the database asleep, `STORE=snapshot flask run` still serves the same 500 rows, the same five chips, and the same panel numbers.
- Deterministic data: fixed seed, no login, no scraped source.

## Non-goals

Accounts, sign-in, roles, image upload, moderation queues, notifications, real-time push, a mobile app, multi-campus tenancy, a long-running server, a search library (no Whoosh, no FTS5), fuzzy typo correction, stemming.

## Anti-goals

These would mean the project is theater, even if it technically runs:

- A "search index" that in practice calls `"x" in text` over the list.
- Comparison numbers that are printed but not measured.
- Importing a search library and calling it "implemented."
- Data structures smuggled into JavaScript so the UI can feel instant — the DSA is Python or it is not the project.
- Two paths that implement slightly different matches, and a "same results" badge that is therefore only usually true.
- A fallback that rewrites the algorithm layer to work offline. If the DSA has to know where the rows came from, the seam is in the wrong place.

## Constraints

- **Python for every structure and algorithm**, non-negotiable. The browser renders; it does not search.
- Vercel runs the app as a **Python function** with a read-only filesystem and non-persistent `/tmp`, so any state that must survive a request belongs in the database. This is a fact of the platform, not a preference.
- **The demo must survive no wifi and a dead database.** A committed snapshot of the 500 rows (`data/snapshot.json`) is the fallback: `STORE=snapshot flask run` serves the same corpus from disk with zero network calls, and the deployed app degrades to the same snapshot, visibly, when Supabase is unreachable. The algorithms, the panel and the numbers do not change.
- GUI required by the rubric; console output cannot be the only evidence.
- Mixed Filipino/English input is normal ("payong", "umbrella", "ID", "cellphone") — tokenization must not assume clean prose.

## Approaches considered

From the shortlist of five, with the ones that lost:

1. **Group availability finder** (sorted interval arrays, sweep/merge, binary search). Best "daily friction" story, strongest structure-versus-naive contrast, but a week-grid UI plus interval edge cases is the highest chance of a half-working demo. Runner-up.
2. **Campus route planner** (weighted graph, Dijkstra vs BFS for fewest transfers). Highest algorithmic ceiling, highest scope risk: the whole route graph and node diagram must be authored before it looks like anything.
3. **Pantry/fridge expiry** (min-heap by expiry, hash map to heap indices). Fast to ship, but the search story is thin — a priority queue with a shopping list attached.
4. **Lost & found with an inverted index — chosen.** Search is the product, so the algorithm is unmissable; the UI is a form, a filter row, a result list, and one metrics panel; the dataset that makes the gap convincing can be generated deterministically. Weaker on personal daily friction, stronger on defense.
5. **Sari-sari credit ledger** (hash map of customers, sorted-by-balance array, binary search by name). Very recognizable local friction, but with 60 customers an array would do everything the hash map does — exactly the "decorative structure" problem.

Why #4 won: it is the only one of the five where the rubric's two required halves are the same feature, and the only one where a panel's "why not just loop?" question is answered by the running program rather than by the student's confidence.

## Decided design

### Stack

- **Python 3.12** (Vercel's default) + **Flask** — one WSGI app at `api/index.py`, which Vercel runs as a Python function. Flask rather than FastAPI because there is no concurrency to win: every request is one database call plus an in-memory search.
- **Supabase Postgres** for `items`, reached with `supabase-py` over the **REST data API** rather than a raw Postgres socket. Serverless functions open many short-lived connections; the REST path avoids pooling entirely, including the transaction pooler's prepared-statement restriction.
- **Tailwind CSS**, compiled locally with the Tailwind CLI into `public/styles.css` and committed. No CSS build step at deploy time.
- **Plain HTML + a thin `public/app.js`** for the UI: `fetch` to the API, render results, no framework, no bundler.
- **Static files served by Flask** (`send_from_directory`), not by a separate CDN layer. One origin, one routing model, so what runs locally is what runs on Vercel.

Reason: every layer between the panel and the algorithm is a place they stop believing you. The `dsa/` package is pure Python — no Flask, no HTTP, no database client — taking lists and dicts and returning lists and dicts, so it can be read aloud and run in a REPL during the defense. Tailwind is a CSS build step and hides nothing that is graded.

### Data model

```python
# dsa/models.py
@dataclass(frozen=True)
class Item:
    id: int
    kind: str            # "lost" | "found"
    title: str           # "Black umbrella, wooden handle"
    description: str
    category: str        # umbrella | id | phone | bag | other
    location: str        # "Covered court, bench 3"
    date_iso: str        # reported date, drives browse order
    status: str          # open | claimed | returned
    reporter: str
    tags: list[str]
    tokens: list[str]    # unique, from the shared tokenizer; derived in memory
                         # at load from title + description + tags + category + location
```

`tokens` is **not** a column. It is computed once when the corpus loads, so the database stores only what a human entered, and both search paths read the same derived list.

### Where the data lives

One table in Supabase. No localStorage, no client-side mode: a Python function has nowhere to keep anything between requests, so the board is shared from the first deploy.

```sql
create table items (
  id bigserial primary key,
  kind text not null check (kind in ('lost','found')),
  title text not null,
  description text not null default '',
  category text not null,
  location text not null default '',
  date_iso date not null,
  status text not null default 'open',
  reporter text not null default '',
  tags jsonb not null default '[]'::jsonb,
  owner_token text not null,
  is_sample boolean not null default false,
  created_at timestamptz not null default now()
);
alter table items enable row level security;  -- and no policies: anon can read nothing
```

**RLS is enabled with no policies, deliberately.** The anon key can do nothing at all; every read and write goes through the function using the **service role key**, which lives only in Vercel's environment variables — never in `public/`, never in the repo, never in chat. One secret, one place.

`owner_token` is minted by the browser on first use and stored in `localStorage`; the server allows `PATCH`/`DELETE` only when it matches. Not security against a determined person — just enough that the public board is not wiped one careless click at a time.

**The index is a cache of the table.** It is built from the rows when a function instance warms up, held in module state, and invalidated by any write; the next search rebuilds it. That is not a workaround, it is the honest architecture of a serverless index, and the panel shows rebuild time so the cost is visible rather than theoretical.

### Offline fallback: the committed snapshot

The failure this project refuses to accept: the room's wifi dies, or the free-tier project is asleep, and there is nothing to show. So the corpus exists twice, generated from one source.

`data/snapshot.json` is committed — the exact 500 rows `scripts/seed.py` produces, same ids, same text, roughly 250 KB, carrying a `seed_version` and the sha256 the generator prints. It is not a second dataset: `scripts/check_snapshot.py` regenerates from the seed and fails if the file has drifted, so the numbers on the panel cannot describe data that no longer exists.

**Two ways it is used, one code path:**

- **`STORE=snapshot flask --app api/index.py run`** — the deliberate offline demo. Zero network calls: template, CSS, JS and rows all come from disk. Writes go to an in-memory list and vanish on restart, which the banner says out loud. This is what runs if the room has no wifi.
- **Automatic degradation, mid-demo as well as at startup** — every store call is wrapped, so if a Supabase read raises (timeout, connection reset, 5xx, paused project) the instance flips to the snapshot *on that request* and answers with results instead of a 500 page. The flip is sticky for the life of the instance — no flapping between corpora mid-demo — and the banner becomes `source: snapshot — database unreachable`. A startup health check still runs, but it is an optimisation now, not the trigger. A **retry database** control probes the table again and, on success, returns the instance to `supabase` and rebuilds the index from the rows.

**Writes while degraded: refused, never faked.** Reads degrade; writes do not. The automatic fallback is read-only: `POST`/`PATCH`/`DELETE` return `503` with `{"error": "not saved", "source": "snapshot"}`, nothing is queued, nothing lands in memory, nothing is retried. The write that tripped the failure may or may not have committed before the connection dropped, so the response says the outcome is unknown and tells the user to check the board once the database answers — resending could duplicate a row that already exists. A row saved minutes *before* the degradation is still in Postgres but not in the committed snapshot, so it leaves the board until recovery; the banner is the explanation, and recovery brings it back. The deliberate offline demo (`STORE=snapshot` from the start) is the different case: there is no database to be ambiguous about, so writes are accepted into memory, and the banner says they are lost on restart.

**What changes in code: nothing algorithmic.** `dsa/` receives a list of `Item` and does not know where it came from. `store/protocol.py` declares `list_items / insert / update / remove`; `store/supabase_store.py` and `store/snapshot_store.py` implement it; the Flask app picks one at startup from `STORE` plus the health check. The fallback is a different loader, not a different search.

**Parity is testable, not asserted.** In snapshot mode `GET /api/audit` must return the same zero mismatches, and the five chips must return the same ids and the same items-examined counts as database mode. If they differ, the snapshot is stale — something `check_snapshot.py` should have caught before the deploy.

**No external assets, and that is a requirement, not a preference.** No Google Fonts, no icon CDN, no script from a URL: system font stack, inline SVG, and `styles.css` committed. An offline page that renders without its font is not offline.

### Structures

1. **Inverted index** — `dict[str, list[int]]` mapping a term to the IDs of items containing it. Posting lists are ascending so intersection is a merge, not a set build. The primary structure, and the thing being defended.
2. **Trie** — prefix tree over the vocabulary, each terminal node carrying a document frequency. Load-bearing for the matching rule: walking to the node for a prefix enumerates *exactly* the terms that start with it, which is how the indexed path implements the same rule as the scan instead of an approximation of it. Also ranks autocomplete by how many items use each term.
3. **Sorted-by-date list** — `list[int]` of item IDs, newest first, maintained by binary-search insertion. Serves browse and date-range filters via binary-search bounds.

Three structures is deliberate: one searches, one resolves prefixes, one is an honest textbook binary search over a sorted list — which pre-empts "an inverted index is a structure, not a search algorithm."

### Matching rule (one rule, both paths)

Stated once, implemented twice, never restated in two dialects.

**Tokenize once.** `tokenize(text)` lowercases, strips punctuation, splits on whitespace, drops stopwords and tokens shorter than 2 characters, and returns unique tokens. Each item's tokens are computed once at load and stored on the item. Both paths read `item.tokens`; the scan never re-tokenizes. The two paths consume identical input, so editing the tokenizer cannot silently desynchronize them.

**Match rule.** A query is normalized by the same `tokenize`. An item matches iff, **for every query token**, at least one of its stored tokens **starts with** that query token. Multi-token queries are AND; a query returns empty only if some token matches nothing.

- Indexed: per query token, walk the trie to the prefix node, enumerate the terms beneath it (`payo` → `payong`, `payongan`), union their posting lists, then intersect the per-token sets.
- Linear: per item, test each stored token against each query token with the same `str.startswith`; the item is examined whether or not it matches.

**Consequences, stated plainly.** Prefix, not substring: `payo` finds `payong`, but `yong` does not. Same rule for both paths — that is what makes the equality claim structural rather than coincidental. Substring or typo-tolerant matching would need n-gram or suffix structures, and is deliberately out of scope.

**Edge cases pinned down, because these are where the paths drift apart:**

- Repeated tokens inside an item — the stored list is unique, so a posting list holds an ID once and the scan does not count the same token twice.
- Empty or all-stopword query — both return browse order, and the panel says *"no query tokens: showing browse, not search results"*, so no speed claim is made off an empty query.
- Fewer than 2 characters — the API rejects it before either path runs, with one message. Distinct from a 2+ character query that tokenizes to nothing but stopwords, which falls into the browse case.
- Case and punctuation — handled once, in the shared normalizer.
- Alias expansion (`payong` ↔ `umbrella`), if it exists at all, happens in shared query normalization *before* either path runs, so it cannot make them disagree.
- Zero matches — both return zero; neither path gets a fallback the other lacks.

### Operations (the rubric's insert / delete / update / retrieve)

- **Insert**: compute `tokens`, `INSERT ... RETURNING id`, append the ID to each term's posting list, add terms to the trie, binary-search-insert into `by_date`. O(terms + log n + n) — the shift in the sorted list is acknowledged, not hidden.
- **Update**: status-only changes are a single row update (cheap). Editing text fields is delete-then-insert in the index, which is the honest cost of a term index.
- **Delete**: for each of the item's terms, scan that posting list and remove the ID — O(sum of document frequencies), the visible price of fast lookup; decrement trie frequencies and prune empty branches; binary-search and splice out of `by_date`.
- **Retrieve**: `search(query, filters)` plus recent-browse from `by_date`.

### Query path

Both paths start from the same normalized query tokens and end at the same result-set contract; only the middle differs.

1. `tokenize(query)` — same function, same stopword list. No path-specific normalization.
2. **Indexed**: per query token, trie-walk to the prefix node, enumerate terms beneath it, union posting lists, intersect the per-token sets. The intersection is the candidate set.
3. **Linear**: per item, `str.startswith` of each stored token against each query token; the item is examined whether or not it matches.
4. Filters — category and status as predicates over the candidate set; date range via binary-search bounds on `by_date` plus membership. Applied identically after either path.
5. **Rank** by (matched query-token count desc, `date_iso` desc) with insertion sort.
6. **Assert equality** — the ID sets from both paths are compared before the response is built. A mismatch is returned and rendered, not swallowed: red banner, offending IDs, the query that produced them. The app may not claim the index is correct while disagreeing with the scan.
7. Serialize.

The scan runs on every query even when the indexed path supplies the results. That costs a full scan per search and is worth it: it *is* the equality check, and it is why no result can be quietly wrong.

### The comparison panel (the defense screen)

Both paths run server-side inside one request, so the panel reports both, no toggle. Two units, and only two, are compared across paths:

- **Items examined** — 500 for the scan (always all of them) against the intersection size for the index. Same noun, same meaning, machine-independent.
- **Median compute time over 20 runs**, measured *inside* the function with `time.perf_counter`, excluding the network. The response also reports round-trip time, labelled separately, precisely so nobody conflates Python compute with Vercel latency.

```
indexed   items examined        2      compute 0.01 ms   (20 runs)
linear    items examined      500      compute 2.02 ms   (20 runs)
ratio                        250x                    ~180x
round trip (network, both)                    84 ms
same result set: 2 items OK  (ids 20, 21)

index: 445 terms - 1,598 trie nodes - rebuild 79 ms for 500 rows
diagnostics, per path, NOT cross-comparable:
  indexed  trie nodes visited 4 - terms enumerated 2 - postings read 27
  linear   prefix tests 3,481
```

The same panel for `pa`, the worst-case chip: indexed 275 items examined, compute 0.09 ms, ratio 1.8×, equality still OK. Two clicks move the demo from 250× to 1.8× with nothing hidden in between — the compute-time ratio, incidentally, does not collapse the way the item ratio does, because the index's per-query floor is a trie walk rather than a scan.

Percentages come from items examined and compute time only. The per-path diagnostics are shown because a panel asks about them second, and they are labelled native to their own path: term lookups and prefix tests are not the same unit, and the panel does not pretend they are.

Complexity, for the defense: the scan is O(N · T) over items × tokens. The index is O(|q| + V_p + P) — prefix walk, vocabulary terms under that prefix, postings read. And the bad case is stated, not hidden: a prefix matching most of the vocabulary produces posting lists close to the item set, so the indexed path approaches the scan, and the panel shows those numbers without embarrassment. Selectivity is what the index buys; when a query has none, neither path is fast and the panel says so.

Search is debounced at 250 ms client-side, with a loading state, because it is now a network request and pretending otherwise would be a lie the UI tells.

### Screens

```
┌ Lost & Found ── [source: supabase] [Clear sample] [+ Report] ─────────┐
│ [ payo▾          ]  category ▾   status ▾   date ▾  [draw from: idx ▾]│
│ try: [payong] [payo] [pa ⚠ worst case] [carved handle] [cellphone]    │
│ ┌──────────────┬─────────────────────────┬──────────────────────────┐ │
│ │ suggestions  │ 2 results               │ ALGORITHMS               │ │
│ │ payong    99 │ ▸ Black umbrella, …     │ items exam:  2  (0.01 ms)│ │
│ │ paypay     8 │   open · bench 7 · 11-20│ items exam: 500 (2.02 ms)│ │
│ │ payung     8 │ ▸ payong itim, carved…  │ ratio: 250x / ~180x      │ │
│ │              │   lost · gym · 11-18    │ OK same 2 results        │ │
│ └──────────────┴─────────────────────────┴──────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

Five one-click chips bracket the range — `payong` and `carved handle` (selective), `payo` (mid), `pa` (worst case, labelled), `cellphone` (near-duplicate cluster) — so a demo never has to type and can step from best case to worst case in two clicks.

- **Report form** (modal): kind, title, description, category, location, date, reporter, tags. Validates, then `POST /api/items`.
- **Item card**: status badge, "I think this is mine" (→ claimed), "Returned" (→ returned), edit, delete. Those are the update and delete paths for the demo.
- **Source badge**: `supabase`, `snapshot (offline demo)` or `snapshot (database unreachable)` next to the item count, so a demo never misrepresents where the rows came from; in the degraded state a **retry database** control sits beside it.
- **Algorithms panel**: the block above, plus an "rebuild index" button that times a full rebuild, and a "clear sample rows" action that deletes `is_sample = true` in one call — so a real board starts empty without dropping the table.

### Deployment (Vercel)

| Setting | Value |
|---|---|
| Framework preset | Flask (detected from `requirements.txt`) |
| Entrypoint | `api/index.py` exposing `app` (WSGI) |
| Python version | 3.12 via `.python-version` |
| Build command | none — `public/styles.css` is committed, Vercel installs `requirements.txt` |
| Environment variables | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| `vercel.json` | not needed |

Flask serves both the API and the static page from `public/`, so there is one origin and no CDN-versus-function routing ambiguity. If the preset's entrypoint detection misbehaves, the documented fallback is file-based functions (`api/*.py`) plus a `vercel.json` route; that is verified with `vercel dev` before the first production deploy rather than discovered after.

**Publish path:** `git init`, push to GitHub, import on Vercel. Every push gets a preview URL, `main` gets production. The workspace is not a git repo yet, so that is step one of the build. `vercel` CLI is the fallback if GitHub is not wanted.

**Two failure modes specific to this stack, and what to do about them:**

- **Free-tier Supabase pauses a project after 7 days of inactivity.** The deployed app no longer dies with it: the first request fails, the snapshot takes over mid-request, and the badge says so. Still worth opening the app a few times in the final month and confirming real rows the day before — a demo running on the snapshot is a fallback, not the product. If it is paused, restoring from the dashboard keeps the data.
- **Cold starts.** The first request to a sleeping function pays index rebuild plus connection setup. Mitigation: the panel shows rebuild time, and the demo starts with one throwaway query so the numbers the panel reads are warm.

**Deployed is not verified.** A successful deploy says the upload succeeded. It does not say the page renders, the assets carry the right content types, the function has its env vars, or search works on that origin. The deployed pass runs after every production deploy.

### Seed data (deliberately messy)

The failure mode to avoid: 500 tidy records like `Black umbrella | bench 3 | 2026-11-18`, where nearly every token appears once, the vocabulary is clean, and the index looks better than any real board would. The seed is built to be hostile to that.

`scripts/seed.py` — a deterministic generator (seeded PRNG, no `random.random` without a seed; same 500 records on every run) inserting with `is_sample = true` in one bulk call, guarded by a count check so it is safe to run twice. Targets it must hit, all checkable in the audit:

| Property | Target | Why it matters |
|---|---|---|
| Register | code-switched Filipino/English, group-chat voice | `nawala payong ko mga mare, naiwan ata sa bench 3 covered court` is what people actually type |
| Noise | emoji, `!!!`, `...`, stretched letters (`payonggg`), casing drift (`PAYONG`), typos (`payung`, `payonh`, `celfone`) | the normalizer is under real pressure, and the scan pays for the same noise |
| Length | mean 14.5 unique tokens per item, max 22 (9,977 raw slots, 27% removed by dedupe) | short records make both paths look cheap |
| Repeated tokens inside one item | every item repeats a token at least twice (title and description both name the object); 65% repeat one 3+ times | exercises the unique-token rule and posting-list dedupe; a bug here shows as count drift between paths |
| Near-duplicate clusters | 5 clusters of 3–5 items describing the same object in different words | one query returns near-identical cards a human must disambiguate, and it strains the equality assertion hardest |
| Vocabulary | 445 distinct terms over 7,241 postings, heavily skewed (top term in 419 of 500 items, long tail of singletons) | a flat distribution is not a vocabulary |
| Low-selectivity prefix `pa` | 25 terms beginning `pa` (payong, paki, papel, pantalon, pasok, pasuyo, pahingi, panlib, panyo…), together in 55% of items | the index's worst case has to be one click away |
| High-selectivity query | a rare pair (`carved handle`) matching 2 items | the best case has to be one click away too |

These are measurements, not ambitions: `python scripts/seed.py --report` prints them from the committed snapshot, and `check_snapshot.py` fails if the snapshot drifts from the generator. Two of the original targets were adjusted down after measurement — the vocabulary is 445 terms rather than the ~1,800 first written down, because 500 short group-chat posts written from a shared pool of nouns, places and contexts simply do not contain 1,800 distinct words. The skew is what the panel needs; the count was a guess.

Near-duplicates carry different IDs and locations, and dates within a few days of each other, so ranking has real work: same match count, recency decides.

Every sample row is flagged and labelled in the UI. Unflagged rows are what a real deployment leaves behind.

### Verification

- **Local pass**: `flask --app api/index.py run` against the Supabase project; search returns both paths' numbers, ids match, insert / update / delete persist across a server restart.
- **Offline pass** (the one that matters most): turn the wifi off entirely, run `STORE=snapshot flask --app api/index.py run`, open the page, press all five chips, hit `/api/audit`, then insert, edit and delete a row. Everything must work with the radio off and the badge must read `snapshot (offline)`.
- **Parity pass**: the same five queries in snapshot mode and in database mode return identical ids and identical items-examined counts. Different numbers mean the snapshot is stale.
- **Mid-demo failure drill**: with the app already running against Supabase, pause the project (or pull the network), then search — results still render from the snapshot, the badge flips, and the panel describes the 500 snapshot rows. A write must return 503 with the unknown-outcome message, not a fake success. Restore the database, press **retry database**, and confirm the badge returns to `supabase` and a row saved before the failure reappears.
- **Equality audit**: `GET /api/audit` runs 50 queries (single token, multi-token, partial prefixes, all-stopword, zero-match, one-character) through both paths and reports mismatches. It must return 0 before the demo, since it is the check a panel will re-run by hand.
- **Worst-case pass**: `pa` shows indexed items examined in the hundreds and the ratio collapsing toward 1× while equality stays OK. The near-duplicate cluster returns every member on both paths — the case where a dedupe or stopword bug hides.
- **Security pass**: with the anon key and no policies, a direct REST request to `items` is denied; the service key never appears in `public/` or the repo; a `PATCH` without the owner token is refused.
- **Deployed pass**: after a production deploy, load the URL, add a record, reload, see it; confirm assets have correct content types and the console is clean; then open the URL on a phone and confirm the same record is there.
- No automated test suite: not requested, and the graded artifact is the running demo. The audit endpoint is a demo feature, not a suite.

## How this gets defended

- **"Why not just loop over the items?"** — the panel, on the projector, for a query matching 2 items out of 500: 2 items examined against 500; 0.01 ms of Python against 2.02 ms.
- **"How do you know the index is right?"** — the scan runs on every query and the result sets are compared before the response leaves; a disagreement is on screen in red, not in a comment.
- **"What does the index cost you?"** — delete a row and point at the posting-list scan; insert one and point at the sorted-list shift and the rebuild timer. Fast reads are paid for on writes.
- **"Isn't the trie just decoration?"** — type `pay` and show suggestions ordered by document frequency, which the dict alone cannot produce.
- **"Is this a real system or a class demo?"** — open the deployed URL, post from a phone, show it on the laptop. Same table, same Python, same numbers.

## What's left to the builder

```
api/index.py            Flask: /api/search, /api/items (GET/POST/PATCH/DELETE), /api/audit, static
dsa/models.py           Item dataclass
dsa/tokenize.py         the one tokenizer + stopwords
dsa/inverted.py         inverted index: dict[str, list[int]]
dsa/trie.py             prefix trie + document frequencies
dsa/by_date.py         binary-search-maintained sorted list of ids
dsa/search.py           indexed path, linear baseline, equality assertion
dsa/rank.py             insertion-sort ranking
store/protocol.py       list_items / insert / update / remove
store/supabase_store.py REST data API via supabase-py
store/snapshot_store.py committed JSON from disk; writes held in memory
data/snapshot.json      the 500 rows, committed, hash-checked
scripts/seed.py         deterministic generator; --emit-snapshot writes the JSON
scripts/check_snapshot.py  regenerates from the seed and fails on drift
public/index.html        Tailwind-built page, app.js, styles.css (committed)
requirements.txt · .python-version · tailwind.config.js · package.json (Tailwind only)
```

Open items, mine to settle unless the user prefers otherwise: the stopword list (short, English + Filipino particles — either way both paths get the same list); whether the alias map (`payong` ↔ `umbrella`) is worth its ten entries (only in shared query normalization if so); and whether `is_sample` rows are hidden from browse by default or shown with a badge.

The user's calls, not mine: publishing through GitHub or the `vercel` CLI, and whether the seed runs against the production project or only local.

Settled in this revision: Python 3.12 + Flask on Vercel, Supabase Postgres as the primary store, Tailwind for CSS, sample rows flagged and clearable, the messy seed targets above, and the offline snapshot as a first-class store implementation rather than a special case.
