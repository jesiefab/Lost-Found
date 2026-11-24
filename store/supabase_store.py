"""Supabase over the REST data API, behind the same protocol as the snapshot.

Two things this module refuses to do:

* Let a hung connection hold the demo hostage. The library's PostgREST default
  is 120 s and its own ``timeout`` parameter is deprecated in 2.34.1, so the
  bound is set on the HTTP client — 5 s, after which the call raises and the
  facade degrades to the snapshot.
* Let an infrastructure failure escape as a generic 500. Everything the client
  raises is mapped onto the store taxonomy (``StoreUnavailable`` for "the
  database is gone", ``ValidationError`` for constraint violations,
  ``StoreError`` for our own query bugs, which must not be masked as an
  outage), so the fallback keeps working without a live project.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

import httpx

from dsa.models import Item

from .protocol import (
    ItemNotFound,
    NotOwner,
    StoreError,
    StoreUnavailable,
    ValidationError,
    drop_tokens,
    fields_of,
    validate_new,
    validate_patch,
)

DEFAULT_TIMEOUT = 5.0
DEFAULT_TABLE = "items"


def credentials() -> tuple[str, str]:
    """The server key, under either name Supabase has shipped it as.

    Newer projects issue `sb_secret_…` as `SUPABASE_SECRET_KEY`; older ones a
    service-role JWT as `SUPABASE_SERVICE_ROLE_KEY`. Both authenticate the same
    way, so read whichever the project was set up with.
    """
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()
    return url, key

# Codes that are the caller's fault rather than the database's.
_CONSTRAINT_PREFIXES = ("22", "23")  # data exception, integrity violation
_QUERY_PREFIX = "PGRST1"  # PostgREST query-parse error: our bug, not an outage
_AUTH_CODES = ("PGRST301", "PGRST302", "42501")  # JWT / permission problems


def _classify(exc: BaseException) -> StoreError:
    """Map whatever the client raised onto the taxonomy the facade understands."""
    if isinstance(exc, httpx.HTTPError):
        detail = str(exc).strip() or type(exc).__name__
        return StoreUnavailable(f"database unreachable: {detail}"[:240])

    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", None) or exc).strip()
    if isinstance(code, str):
        if code in _AUTH_CODES:
            return StoreUnavailable(f"database refused the request ({code}): {message}"[:240])
        if code.startswith(_CONSTRAINT_PREFIXES):
            return ValidationError(f"{message or 'rejected by the database'} ({code})"[:240])
        if code.startswith(_QUERY_PREFIX):
            return StoreError(f"query error {code}: {message}"[:240])
        return StoreUnavailable(f"database error {code}: {message}"[:240])

    return StoreUnavailable(f"database unreachable: {type(exc).__name__}: {message}"[:240])


def _as_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError("id must be an integer") from None


def _build_client(url: str, key: str, timeout: float):
    """Build the client without trusting the library's defaults.

    ``ClientOptions`` (the unsuffixed dataclass) makes ``create_client`` raise
    ``AttributeError: 'ClientOptions' object has no attribute 'storage'`` in
    2.34.1; ``SyncClientOptions`` is the one the sync client expects.
    """
    try:
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions
    except ImportError as exc:  # pragma: no cover - requirements.txt installs it
        raise StoreUnavailable(
            "supabase-py is not installed (pip install -r requirements.txt)"
        ) from exc

    http_client = httpx.Client(timeout=httpx.Timeout(timeout))
    try:
        client = create_client(url, key, SyncClientOptions(httpx_client=http_client))
    except Exception as exc:
        http_client.close()
        raise StoreUnavailable(f"Supabase client could not be built: {exc}"[:240]) from exc
    return client, http_client


class SupabaseStore:
    """The primary store. Wraps, never swallows."""

    source = "supabase"
    writable = True

    def __init__(
        self,
        client: Any = None,
        *,
        http_client: Any = None,
        table_name: str = DEFAULT_TABLE,
        reason: str = "",
    ) -> None:
        self._client = client
        self._http = http_client
        self._table = table_name
        self._reason = reason
        self.last_error = ""

    @classmethod
    def from_env(cls, *, timeout: float = DEFAULT_TIMEOUT) -> "SupabaseStore":
        """A store even when the env vars are missing.

        Missing configuration degrades to the snapshot like any outage; it must
        not stop the app from booting into its fallback.
        """
        url, key = credentials()
        if not url or not key:
            return cls(
                None,
                reason="Supabase is not configured: set SUPABASE_URL and "
                "SUPABASE_SECRET_KEY (or the older SUPABASE_SERVICE_ROLE_KEY)",
            )
        client, http_client = _build_client(url, key, timeout)
        return cls(client, http_client=http_client)

    # -- state -----------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self._client is not None

    @property
    def state(self) -> dict:
        return {
            "source": self.source,
            "writable": self.writable,
            "configured": self.configured,
            "reason": self._reason,
            "last_error": self.last_error,
        }

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    # -- plumbing --------------------------------------------------------
    def _table_client(self):
        if self._client is None:
            raise StoreUnavailable(self._reason or "Supabase is not configured")
        return self._client.table(self._table)

    def _guard(self, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except StoreError:
            raise
        except Exception as exc:  # translated, never swallowed
            self.last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            raise _classify(exc) from exc

    def _fetch_row(self, item_id: int) -> dict:
        response = (
            self._table_client().select("*").eq("id", item_id).limit(1).execute()
        )
        rows = response.data or []
        if not rows:
            raise ItemNotFound(f"item {item_id} does not exist")
        return rows[0]

    # -- reads -----------------------------------------------------------
    def list_items(self) -> list[Item]:
        def operation():
            response = self._table_client().select("*").order("id").execute()
            return [drop_tokens(Item.from_row(row)) for row in (response.data or [])]

        return self._guard(operation)

    def get(self, item_id: int) -> Item | None:
        try:
            wanted = int(item_id)
        except (TypeError, ValueError):
            return None

        def operation():
            response = (
                self._table_client().select("*").eq("id", wanted).limit(1).execute()
            )
            rows = response.data or []
            return drop_tokens(Item.from_row(rows[0])) if rows else None

        return self._guard(operation)

    def health(self, force: bool = False) -> bool:
        """One cheap real query. Costs the same transport as a read, so a
        paused project and a broken read agree — which is the point."""

        def operation():
            response = self._table_client().select("id").limit(1).execute()
            return response is not None and getattr(response, "data", None) is not None

        return self._guard(operation)

    def probe(self, force: bool = False) -> dict:
        self.health(force=force)
        return self.state

    # -- writes ----------------------------------------------------------
    def insert(self, item: Item) -> Item:
        if not item.owner_token:
            raise ValidationError("owner_token is required")
        clean = validate_new(fields_of(item))
        payload = {
            "kind": clean["kind"],
            "title": clean["title"],
            "description": clean["description"],
            "category": clean["category"],
            "location": clean["location"],
            "date_iso": clean["date_iso"],
            "status": clean["status"],
            "reporter": clean["reporter"],
            "tags": list(clean["tags"]),
            "owner_token": item.owner_token,
            "is_sample": bool(item.is_sample),
        }

        def operation():
            response = self._table_client().insert(payload).execute()
            rows = response.data or []
            if not rows:
                raise StoreError("Supabase accepted the insert but returned no row")
            return drop_tokens(Item.from_row(rows[0]))

        return self._guard(operation)

    def update(
        self, item_id: int, changes: Mapping[str, Any], owner_token: str
    ) -> Item:
        wanted = _as_id(item_id)
        clean = validate_patch(changes)

        def operation():
            row = self._fetch_row(wanted)
            if not owner_token or owner_token != (row.get("owner_token") or ""):
                raise NotOwner("owner token does not match this item")
            if not clean:
                return drop_tokens(Item.from_row(row))
            payload = dict(clean)
            if "tags" in payload:
                payload["tags"] = list(payload["tags"])
            response = (
                self._table_client()
                .update(payload)
                .eq("id", wanted)
                .eq("owner_token", owner_token)
                .execute()
            )
            rows = response.data or []
            if not rows:
                raise StoreError("the update matched no row; the item changed mid-edit")
            return drop_tokens(Item.from_row(rows[0]))

        return self._guard(operation)

    def delete(self, item_id: int, owner_token: str) -> Item:
        wanted = _as_id(item_id)

        def operation():
            row = self._fetch_row(wanted)
            if not owner_token or owner_token != (row.get("owner_token") or ""):
                raise NotOwner("owner token does not match this item")
            self._table_client().delete().eq("id", wanted).eq(
                "owner_token", owner_token
            ).execute()
            return drop_tokens(Item.from_row(row))

        return self._guard(operation)

    def clear_samples(self) -> int:
        def operation():
            rows = (
                self._table_client().select("id").eq("is_sample", True).execute().data
                or []
            )
            if rows:
                self._table_client().delete().eq("is_sample", True).execute()
            return len(rows)

        return self._guard(operation)
