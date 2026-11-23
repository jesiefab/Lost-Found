"""The Flask app Vercel runs: one origin for the API and the page.

Store selection happens once per function instance. The search engine is built
lazily from whatever the store returns and invalidated by any write — the
documented cost of keeping an index in memory on a serverless platform, with
`build_ms` reported so the cost is visible rather than theoretical.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, send_from_directory

from dsa import MIN_QUERY_CHARS, Filters, Item, SearchEngine
from store import (
    ItemNotFound,
    NotOwner,
    SnapshotStore,
    StoreError,
    StoreFacade,
    StoreReadOnly,
    SupabaseStore,
    ValidationError,
    normalize_tags,
)

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def _build_store():
    """`STORE=snapshot` is the deliberate offline demo; otherwise Supabase with
    the snapshot as a fallback the facade switches to mid-request."""
    mode = (os.environ.get("STORE") or "").strip().lower()
    if mode == "snapshot":
        return SnapshotStore(writable=True, reason="offline demo")
    primary = SupabaseStore.from_env()
    return StoreFacade(
        primary, lambda reason: SnapshotStore(writable=False, reason=reason)
    )


STORE = _build_store()
_engine: SearchEngine | None = None
_engine_lock = Lock()


def _engine_for_request() -> SearchEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SearchEngine(STORE.list_items())
        return _engine


def _invalidate() -> None:
    global _engine
    with _engine_lock:
        _engine = None


app = Flask(__name__, static_folder=None)


# -- plumbing ------------------------------------------------------------
def _token(payload: dict | None = None) -> str:
    candidate = (payload or {}).get("owner_token")
    if not candidate:
        candidate = request.headers.get("X-Owner-Token") or request.args.get("token")
    return str(candidate or "").strip()


def _error(message: str, status: int, **extra):
    body: dict = {"error": message, "store": STORE.state}
    body.update(extra)
    return jsonify(body), status


@app.after_request
def _no_store(response):
    # Search results and store state change with every write; caching them
    # would let a stale panel outlive the numbers it is claiming.
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(StoreError)
def _store_error(exc: StoreError):
    status = 500
    if isinstance(exc, ValidationError):
        status = 400
    elif isinstance(exc, NotOwner):
        status = 403
    elif isinstance(exc, ItemNotFound):
        status = 404
    elif isinstance(exc, StoreReadOnly):
        status = 503

    extra: dict = {}
    if isinstance(exc, StoreReadOnly):
        extra["outcome_unknown"] = exc.outcome_unknown
        extra["hint"] = (
            "the write may have reached the database before the connection "
            "dropped; reload once the database answers"
            if exc.outcome_unknown
            else "the board is running from the committed snapshot, which is read-only"
        )
    return _error(str(exc), status, **extra)


# -- reads ---------------------------------------------------------------
@app.get("/api/health")
def health():
    force = (request.args.get("force") or "").lower() in ("1", "true", "yes")
    return jsonify({"ok": True, "store": STORE.probe(force=force)})


@app.get("/api/search")
def search():
    query = request.args.get("q", "")
    if query.strip() and len(query.strip()) < MIN_QUERY_CHARS:
        return _error(
            "a query needs at least 2 characters before either path runs", 400
        )
    filters = Filters(
        category=request.args.get("category") or None,
        status=request.args.get("status") or None,
        date_from=request.args.get("from") or None,
        date_to=request.args.get("to") or None,
    )
    result = _engine_for_request().search(query, filters)
    payload = result.to_dict()
    payload["store"] = STORE.state
    return jsonify(payload)


@app.get("/api/suggest")
def suggest():
    prefix = (request.args.get("prefix") or "").strip().lower()
    try:
        limit = min(max(int(request.args.get("limit", 8)), 1), 20)
    except (TypeError, ValueError):
        limit = 8
    return jsonify(
        {
            "prefix": prefix,
            "suggestions": _engine_for_request().suggestions(prefix, limit),
        }
    )


@app.get("/api/audit")
def audit():
    payload = _engine_for_request().audit().to_dict()
    payload["store"] = STORE.state
    return jsonify(payload)


# -- writes: the rubric's insert / update / delete ------------------------
@app.post("/api/items")
def create_item():
    payload = request.get_json(silent=True) or {}
    item = Item(
        id=0,
        kind=str(payload.get("kind") or "").strip(),
        title=str(payload.get("title") or ""),
        description=str(payload.get("description") or ""),
        category=str(payload.get("category") or "other").strip() or "other",
        location=str(payload.get("location") or ""),
        date_iso=str(payload.get("date_iso") or ""),
        status=str(payload.get("status") or "open").strip() or "open",
        reporter=str(payload.get("reporter") or ""),
        tags=normalize_tags(payload.get("tags")),
        owner_token=_token(payload),
    )
    created = STORE.insert(item)
    _invalidate()
    return jsonify({"item": created.to_public(), "store": STORE.state}), 201


@app.patch("/api/items/<int:item_id>")
def update_item(item_id: int):
    payload = request.get_json(silent=True) or {}
    changes = {key: value for key, value in payload.items() if key != "owner_token"}
    updated = STORE.update(item_id, changes, _token(payload))
    _invalidate()
    return jsonify({"item": updated.to_public(), "store": STORE.state})


@app.delete("/api/items/<int:item_id>")
def delete_item(item_id: int):
    removed = STORE.delete(item_id, _token())
    _invalidate()
    return jsonify({"deleted": removed.to_public(), "store": STORE.state})


@app.post("/api/samples/clear")
def clear_samples():
    removed = STORE.clear_samples()
    _invalidate()
    return jsonify({"removed": removed, "store": STORE.state})


# -- the page ------------------------------------------------------------
@app.get("/")
def home():
    if (PUBLIC / "index.html").is_file():
        return send_from_directory(PUBLIC, "index.html")
    return jsonify(
        {
            "service": "lost & found board",
            "ui": "not built yet — public/index.html is the next piece",
            "endpoints": [
                "/api/search?q=&category=&status=&from=&to=",
                "/api/items (POST)",
                "/api/items/<id> (PATCH, DELETE)",
                "/api/suggest?prefix=",
                "/api/audit",
                "/api/health?force=1",
                "/api/samples/clear (POST)",
            ],
            "store": STORE.state,
        }
    )


@app.get("/<path:asset>")
def static_asset(asset: str):
    return send_from_directory(PUBLIC, asset, max_age=3600)
