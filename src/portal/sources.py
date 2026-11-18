"""When a dataset's source tables last changed, from Unity Catalog metadata (Tables API). No SQL, no warehouse.

Called as the app's service principal, because viewers often can't read the gold and silver tables behind the
platinum views. Views are followed to the tables they read (`view_dependencies`); a view's own `updated_at` is only
its DDL time, so it is never reported. For managed Delta tables `updated_at` moves on every write.

Each base table has a `kind`: "managed" (its `updated_at` is the last write), "live" (a FOREIGN, Lakehouse Federation
table, read from the remote system at query time, so current as of each fetch), "external" (written outside Unity
Catalog, so the change time isn't tracked), "none" (a view known to read no table at all, such as a generated
calendar: nothing to time, nothing to wait for), "static" (in a catalog listed under `static_catalogs` in
environments.yml, whose data never changes, such as `samples`: never looked up) or "unknown" (no permission, not
found, timed out or over the cap).
Everything fails soft: a table we can't read or find is "unknown" with `updated_at: None`.

With only BROWSE, Unity Catalog returns a view's type but not its `view_dependencies`. So the deploy pipeline writes
`src/sources_map.json` (scripts/build_sources_map.py, run with full metadata access): what each view reads. When it is
there and built for this environment, views are followed through it; tables are still looked up live.

A view is "none" only when it is KNOWN to read no table: the map lists it with no dependencies, or a lookup with full
metadata access returned a dependency list that holds no table. A BROWSE-only lookup returns no `view_dependencies`
at all, which says nothing, so that view stays "unknown".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path

from .registry import Dashboard, Dataset, strip_sql_comments_and_strings, tables_in
from .settings import DATE_TOKENS, STATIC_CATALOGS

log = logging.getLogger("portal.sources")
TABLE_TTL = 600          # a table's updated_at is re-read after 10 minutes
VIEW_TTL = 6 * 3600      # what a view reads rarely changes; re-read after 6 hours
MAX_DEPTH = 5            # view → view → … at most this deep
MAX_TABLES = 40          # tables visited per dataset reference, to bound the API calls
TIMEOUT = 10.0           # seconds for the whole /sources request; unresolved tables come back unknown
# The freshness parser covers plain FROM/JOIN references. Refresh anything with opaque inputs,
# including quoted identifiers, comma-qualified references, UDFs, and common changing SQL expressions.
REFRESH_UNCERTAIN = re.compile(
    r"\b(?:current_(?:date|timestamp|time|catalog|schema|database|user|timezone)"
    r"|localtimestamp|now|curdate|getdate|getutcdate|sysdate|today|session_user|user|rand|random|randn|uuid"
    r"|monotonically_increasing_id|spark_partition_id)\b"
    r"|,\s*\w+\s*\.\s*\w+\s*\.\s*\w+|\b\w+\s*\.\s*\w+\s*\(",
    re.IGNORECASE,
)
VIEW_TYPES = {"VIEW", "METRIC_VIEW"}  # hold no data: followed to the tables they read
# Tables whose updated_at moves when their data is written ("managed"). FOREIGN (federated) tables are "live": their
# updated_at is only a metadata sync, but every query reads the remote system. EXTERNAL tables can be written without
# Unity Catalog knowing, so their time isn't tracked. Neither is timed, and neither hides the managed tables' time.
TRUSTED_TYPES = {"MANAGED", "MATERIALIZED_VIEW", "STREAMING_TABLE"}
LIVE_TYPES = {"FOREIGN"}
EXTERNAL_TYPES = {"EXTERNAL"}
# data_source_format of a foreign table -> the system it is read from ("live (Snowflake)"); others say "federated"
VIA = {"SNOWFLAKE": "Snowflake", "SQLSERVER": "SQL Server", "SQLDW": "Azure Synapse", "POSTGRESQL": "PostgreSQL",
       "MYSQL": "MySQL", "REDSHIFT": "Redshift", "BIGQUERY": "BigQuery", "ORACLE": "Oracle", "TERADATA": "Teradata",
       "DATABRICKS": "Databricks", "SALESFORCE": "Salesforce", "SALESFORCE_DATA_CLOUD": "Salesforce Data Cloud"}

# name -> (expires, kind, value): kind "view" (value = dependency names), "table" (managed; value = updated_at in
# seconds), "live" (value = the remote system's name or None), "external" (value = None) or "unknown" (value = None)
# (a view found to read no table is cached as "view" with no dependencies; resolve() turns it into "none")
_cache: dict[str, tuple[float, str, object]] = {}
_guard = threading.Lock()
_warned: set[str] = set()
MAP_PATH = Path(__file__).resolve().parent.parent / "sources_map.json"
_map: dict[str, list[str]] = {}  # view -> the tables and views it reads, from the deploy-time map (empty: none loaded)


def load_map(env: str, path: Path = MAP_PATH) -> int:
    """Loads the deploy-time view map if it exists and was built for `env`. Returns the number of views loaded."""
    global _map
    _map = {}
    if not path.exists():
        log.info("no source map at %s; views are followed with the Tables API only", path.name)
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("env") != env:
            log.warning("source map %s is for %r, not %r; ignored", path.name, doc.get("env"), env)
            return 0
        _map = {k.lower(): [d.lower() for d in v] for k, v in (doc.get("views") or {}).items()}
    except Exception as e:  # a broken map must not stop the app: behave as if there were none
        log.warning("source map %s unreadable, ignored: %s", path.name, str(e)[:200])
        return 0
    log.info("source map for %s (built %s): %d views", env, doc.get("generated_at"), len(_map))
    return len(_map)


def _warn_once(name: str, e: Exception) -> None:
    with _guard:
        if name in _warned:
            return
        _warned.add(name)
    log.warning("source metadata for %s unavailable: %s", name, str(e)[:200])


def describe(info) -> tuple[str, str, object]:
    """(table_type, kind, value) for one TableInfo; kind and value as in the cache (TTL aside)."""
    ttype = str(getattr(info.table_type, "value", info.table_type) or "").upper()
    if ttype in VIEW_TYPES:
        deps = [d.table.table_full_name.lower() for d in ((info.view_dependencies and info.view_dependencies.dependencies) or [])
                if d.table and d.table.table_full_name]  # function dependencies are ignored
        return ttype, "view", deps
    if ttype in LIVE_TYPES:
        fmt = str(getattr(info.data_source_format, "value", info.data_source_format) or "").upper()
        return ttype, "live", VIA.get(fmt.removesuffix("_FORMAT"))
    if ttype not in TRUSTED_TYPES:  # EXTERNAL, or a type we don't know: not timed
        return ttype, "external", None
    if info.updated_at:
        return ttype, "table", info.updated_at / 1000
    return ttype, "unknown", None


def lookup(client, name: str) -> tuple[str, object]:
    """One table or view's metadata, cached. A view in the deploy-time map isn't looked up. Never raises."""
    if name in _map:
        return "view", _map[name]
    now = time.time()
    hit = _cache.get(name)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        info = client.tables.get(name, include_browse=True)
        _, kind, value = describe(info)
        if kind == "view" and not value and info.view_dependencies is None:
            kind = "unknown"  # BROWSE only: no dependency information, which is not "reads no table"
        entry = (now + (TABLE_TTL if kind in ("table", "unknown") else VIEW_TTL), kind, value)
    except Exception as e:  # no permission, not found, network: unknown, and say so once in the log
        _warn_once(name, e)
        entry = (now + TABLE_TTL, "unknown", None)
    _cache[name] = entry
    return entry[1], entry[2]


def _table(name: str, kind: str, value=None) -> dict:
    """One base table as /sources reports it: {name, kind, updated_at} (+ `via` for a live table)."""
    if kind == "table":
        return {"name": name, "kind": "managed", "updated_at": value}
    known = ("live", "external", "none", "static")
    t = {"name": name, "kind": kind if kind in known else "unknown", "updated_at": None}
    if kind == "live":
        t["via"] = value
    return t


def resolve(client, name: str, seen: set[str] | None = None, look=None) -> list[dict]:
    """The base tables behind `name` (itself if it is a table): [{name, kind, updated_at (epoch seconds or None)}].

    `seen`, if given, collects every table and view looked up (scripts/grant_app_access.py uses it). `look(name)` ->
    (kind, value) replaces the cached `lookup` (scripts/build_sources_map.py uses it to record what it finds)."""
    out: dict[str, dict] = {}
    seen = set() if seen is None else seen
    look = look or (lambda n: lookup(client, n))

    def walk(n: str, depth: int) -> None:
        if n.split(".")[0] in STATIC_CATALOGS:  # data never changes: nothing to look up, time or grant
            out[n] = _table(n, "static")
            return
        if n in seen or len(seen) >= MAX_TABLES:
            if n not in seen:
                out.setdefault(n, _table(n, "unknown"))  # over the cap: listed, but unknown
            return
        seen.add(n)
        kind, value = look(n)
        if kind == "view":
            if depth >= MAX_DEPTH:
                out.setdefault(n, _table(n, "unknown"))  # too deep
                return
            if not value:  # known to read no table (the map, or a full-access lookup, said so)
                out.setdefault(n, _table(n, "none"))
                return
            for dep in value:
                walk(dep, depth + 1)
        else:
            out[n] = _table(n, kind, value)

    walk(name.lower(), 0)
    return [out[k] for k in sorted(out)]


def _summary(note: str, tables: list[dict]) -> dict:
    """source_updated_at = the newest managed table's time, if there is one and no table is unknown (an unknown table
    could be the one that changed). Live and external tables don't block it, but are flagged: `live` (some table is
    read live, so the time can't speak for it) and `partial` (the time leaves some tables out, or one isn't tracked).
    A "none" table (a view that reads no table) has nothing to time and blocks nothing; a dataset whose tables are all
    "none" has no time and `no_source: True`. A "static" table (its catalog's data never changes) blocks nothing
    either; a dataset whose tables are all "static" (or "none") has no time and `static: True`."""
    kinds = {t["kind"] for t in tables}
    managed = [t["updated_at"] for t in tables if t["kind"] == "managed"]
    newest = max(managed) if managed and "unknown" not in kinds else None
    live = "live" in kinds
    partial = "external" in kinds or (live and bool(managed))
    no_source = bool(tables) and kinds == {"none"}
    static = "static" in kinds and kinds <= {"static", "none"}
    return {"source_note": note, "tables": tables, "source_updated_at": newest, "live": live, "partial": partial,
            "no_source": no_source, "static": static}


async def for_datasets(datasets: dict[str, Dataset], client, timeout: float = TIMEOUT) -> dict[str, dict]:
    """{dataset id: {source_note, tables: [{name, kind, updated_at}], source_updated_at, live, partial, no_source,
    static}} within `timeout` seconds."""
    refs = {ds_id: tables_in(ds.sql) for ds_id, ds in datasets.items()}
    resolved = await _resolve_all(refs, lambda name: resolve(client, name), timeout)
    out = {}
    for ds_id, ns in refs.items():
        merged: dict[str, dict] = {}
        for n in ns:
            for t in resolved[n]:  # one reference can leave a table unknown (over its cap) that another resolved
                if t["name"] not in merged or merged[t["name"]]["kind"] == "unknown":
                    merged[t["name"]] = t
        out[ds_id] = _summary(datasets[ds_id].source, [merged[k] for k in sorted(merged)])
    return out


async def _resolve_all(refs: dict[str, list[str]], read, timeout: float) -> dict[str, list[dict]]:
    names = sorted({name for names in refs.values() for name in names})
    tasks = {n: asyncio.create_task(asyncio.to_thread(read, n)) for n in names}
    if tasks:
        await asyncio.wait(tasks.values(), timeout=timeout)
    resolved: dict[str, list[dict]] = {}
    for n, task in tasks.items():
        if task.done() and not task.cancelled() and task.exception() is None:
            resolved[n] = task.result()
        else:  # still running (it keeps going in its thread and fills the cache for next time) or failed
            resolved[n] = [_table(n, "unknown")]
    return resolved


def _refresh_refs(dashboard: Dashboard, ds: Dataset) -> list[str]:
    if ds.refresh == "always" or "`" in ds.sql or REFRESH_UNCERTAIN.search(strip_sql_comments_and_strings(ds.sql)):
        return []
    if any((dashboard.params.get(name) or {}).get("default") in DATE_TOKENS for name in ds.params):
        return []
    return tables_in(ds.sql)


def _read_refresh_source(client, name: str) -> list[dict]:
    if name.split(".")[0] in STATIC_CATALOGS:
        return [_table(name, "static")]
    try:
        info = client.tables.get(name, include_browse=True)
        table_type = getattr(info.table_type, "value", info.table_type)
        data_format = getattr(info.data_source_format, "value", info.data_source_format)
        if table_type == "MANAGED" and data_format == "DELTA" and info.updated_at:
            return [_table(name, "table", info.updated_at / 1000)]
    except Exception as exc:
        _warn_once(name, exc)
    return [_table(name, "unknown")]


async def refresh_checks(dashboard: Dashboard, datasets: dict[str, Dataset], client, timeout: float = TIMEOUT) -> dict:
    """Read each direct source once, bypassing the display cache. None means a query must run."""
    refs = {ds_id: _refresh_refs(dashboard, ds) for ds_id, ds in datasets.items()}
    resolved = await _resolve_all(refs, lambda name: _read_refresh_source(client, name), timeout)
    checks = {}
    for ds_id, names in refs.items():
        tables = [resolved[name][0] for name in names]
        checks[ds_id] = (
            max(table["updated_at"] or 0 for table in tables)
            if tables and all(table["kind"] in ("managed", "static") for table in tables)
            else None
        )
    return checks
