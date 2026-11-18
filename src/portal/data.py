"""Runs dataset SQL on the SQL warehouse (Statement Execution API) and caches the results."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import date

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementParameterListItem, StatementState

from .registry import Dashboard, Dataset
from .settings import WARM, now_local, resolve_default

log = logging.getLogger("portal.data")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
MAX_ROWS = int(os.getenv("PORTAL_MAX_ROWS", "500000"))
WARM_ENABLED = os.getenv("PORTAL_WARM", "1") != "0"  # scripts/run_local.ps1 turns background warming off
QUERY_TIMEOUT = int(os.getenv("PORTAL_QUERY_TIMEOUT", "600"))  # seconds; the statement is cancelled after this

_cache: dict[str, tuple[float, float, dict]] = {}  # key -> (expires, fetched_at, payload)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class QueryError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def bind(dashboard: Dashboard, ds: Dataset, raw: dict) -> list[StatementParameterListItem]:
    items = []
    for name in ds.params:
        spec = dashboard.params.get(name) or {}
        value = raw.get(name) or resolve_default(spec.get("default"))
        items.append(StatementParameterListItem(
            name=name, type=str(spec.get("type", "STRING")).upper(), value=None if value in (None, "") else str(value),
        ))
    return items


def run_sql(client: WorkspaceClient, sql: str, params: list[StatementParameterListItem]) -> dict:
    if not WAREHOUSE_ID:
        raise QueryError("DATABRICKS_WAREHOUSE_ID is not set")
    r = client.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE_ID, parameters=params or None, wait_timeout="30s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY, on_wait_timeout=None,
    )
    deadline = time.time() + QUERY_TIMEOUT
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() > deadline:
            client.statement_execution.cancel_execution(r.statement_id)
            raise QueryError(f"Query took longer than {QUERY_TIMEOUT // 60} minutes and was stopped")
        time.sleep(2)
        r = client.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if r.status.error else str(r.status.state)
        code = getattr(r.status.error, "error_code", "") if r.status.error else ""
        raise QueryError(msg, getattr(code, "value", code))
    columns = [c.name for c in r.manifest.schema.columns]
    rows = list((r.result and r.result.data_array) or [])
    chunk = r.result
    while chunk is not None and chunk.next_chunk_index is not None and len(rows) < MAX_ROWS:
        chunk = client.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk.next_chunk_index)
        rows.extend(chunk.data_array or [])
    cut = len(rows) > MAX_ROWS or bool(r.manifest.truncated)
    return {"columns": columns, "rows": rows[:MAX_ROWS], "cut": cut}


def cache_key(dashboard: Dashboard, ds: Dataset, who: str, params: list[StatementParameterListItem]) -> str:
    return json.dumps([dashboard.slug, ds.id, who, [(p.name, p.value) for p in params]])


def fetch(dashboard: Dashboard, ds: Dataset, client: WorkspaceClient, who: str, raw_params: dict, refresh: bool = False) -> dict:
    if ds.todo:  # not connected yet (decision 0011); app.py serves a local snapshot preview instead, never this
        raise QueryError(f"{ds.id} isn't connected to Databricks yet (todo in dashboard.yml)")
    params = bind(dashboard, ds, raw_params)
    key = cache_key(dashboard, ds, who, params)
    hit = _cache.get(key)
    if hit and not refresh and hit[0] > time.time():
        return {**hit[2], "fetched_at": hit[1], "expires_at": hit[0], "cached": True}
    with _lock(key):  # one query per key at a time; others wait and reuse it
        hit = _cache.get(key)
        if hit and not refresh and hit[0] > time.time():
            return {**hit[2], "fetched_at": hit[1], "expires_at": hit[0], "cached": True}
        t0 = time.time()
        payload = run_sql(client, ds.sql, params)
        log.info("ran %s/%s for %s: %d rows in %.1fs", dashboard.slug, ds.id, who if who in ("app", "shared") else "user",
                 len(payload["rows"]), time.time() - t0)
        now = time.time()
        _cache[key] = (now + ds.cache_ttl, now, payload)
        return {**payload, "fetched_at": now, "expires_at": now + ds.cache_ttl, "cached": False}


def prune() -> None:
    now = time.time()
    for k in [k for k, v in _cache.items() if v[0] < now - 3600]:
        _cache.pop(k, None)


def data_through(ds: Dataset, payload: dict) -> str | None:
    """Latest valid event date actually returned, separate from when the query was fetched."""
    if not ds.data_through or ds.data_through not in payload.get("columns", []):
        return None
    index = payload["columns"].index(ds.data_through)
    days = []
    for row in payload.get("rows", []):
        try:
            days.append(date.fromisoformat(str(row[index])).isoformat())
        except (ValueError, IndexError, TypeError):
            continue
    return max(days) if days else None


def _warm_slot() -> str | None:
    """The most recent scheduled warm time that has passed today (weekdays only), as 'YYYY-MM-DD HH:MM'."""
    now = now_local()
    if now.weekday() > 4:
        return None
    passed = [t for t in WARM.get("times", []) if t <= now.strftime("%H:%M")]
    return f"{now.date()} {max(passed)}" if passed else None


async def warm_datasets(dashboards: dict[str, Dashboard], app_client_factory, env: str) -> None:
    """Background refresh, as the app's service principal, so readers don't wait on slow sources.

    - auth: app datasets are re-run every cache_ttl.
    - cache: shared datasets with a `warm:` list are re-run for each listed parameter set at the times in
      src/environments.yml. If the service principal can't read the data, the warning is logged and the first
      viewer's own query fills the shared cache instead.
    """
    next_run: dict[str, float] = {}
    scheduled = WARM_ENABLED and env in WARM.get("environments", [])
    started, last_slot = False, _warm_slot()
    while True:
        prune()
        for d in dashboards.values():
            for ds in d.datasets.values():
                key = f"{d.slug}/{ds.id}"
                if ds.todo or ds.auth != "app" or not ds.background or next_run.get(key, 0) > time.time():
                    continue
                next_run[key] = time.time() + max(ds.cache_ttl - 300, 300)
                try:
                    await asyncio.to_thread(fetch, d, ds, app_client_factory(), "app", {}, True)
                except Exception as e:  # keep warming the others
                    log.warning("warm %s failed: %s", key, e)
                    next_run[key] = time.time() + 900
        slot = _warm_slot()
        if scheduled and (not started or (slot and slot != last_slot)):
            startup = not started
            started, last_slot = True, slot
            for d in dashboards.values():
                for ds in d.datasets.values():
                    if ds.warm_at == "startup" and not startup:
                        continue
                    for entry in [] if ds.todo else ds.warm:
                        try:
                            await asyncio.to_thread(fetch, d, ds, app_client_factory(), "shared", entry, True)
                        except Exception as e:
                            log.warning("warm %s/%s %s failed: %s", d.slug, ds.id, entry, str(e)[:300])
        await asyncio.sleep(60)
