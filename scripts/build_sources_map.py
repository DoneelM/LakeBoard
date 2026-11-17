"""Writes src/sources_map.json: what each view behind the live dashboards reads, for the freshness label.

The app's service principal has only BROWSE on the catalogs, and with BROWSE Unity Catalog returns a view's type but
not its `view_dependencies`. So the deploy pipeline, which can read full metadata, follows every view here and the app
uses the result (src/portal/sources.py). Tables are not timed here: the app still reads each table's `updated_at` live.

    python scripts/build_sources_map.py --env dev                       # pipeline: DATABRICKS_HOST / DATABRICKS_TOKEN
    python scripts/build_sources_map.py --env dev --profile <profile> --out <path>

Metadata only (Tables API): no SQL, no warehouse. The pipeline step may fail without blocking a deploy; the app then
follows views itself, as before.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from portal.registry import load_all, tables_in  # noqa: E402
from portal.sources import MAP_PATH, describe, resolve  # noqa: E402


def references(env: str) -> set[str]:
    """Every table and view named in a dataset of a dashboard live in `env` (catalogs already localised)."""
    refs: set[str] = set()
    for d in load_all(env=env).values():
        if d.errors or env not in d.environments:
            continue
        for ds in d.datasets.values():
            refs.update(tables_in(ds.sql))
    return refs


def build(client, refs: set[str], env: str) -> tuple[dict, list[str]]:
    """({generated_at, env, views: {view: [deps]}, types: {table: table_type}}, names whose lookup failed)."""
    views: dict[str, list[str]] = {}
    types: dict[str, str] = {}
    failed: dict[str, str] = {}
    memo: dict[str, tuple[str, object]] = {}

    def look(name: str) -> tuple[str, object]:
        if name not in memo:
            try:
                ttype, kind, value = describe(client.tables.get(name, include_browse=True))
            except Exception as e:  # no permission, not found: left out of the map, the app looks it up itself
                failed[name] = type(e).__name__
                memo[name] = ("unknown", None)
                return memo[name]
            if kind == "view":
                views[name] = value
            else:
                types[name] = ttype or "UNKNOWN"
            memo[name] = (kind, value)
        return memo[name]

    for ref in sorted(refs):
        resolve(None, ref, look=look)  # same walk, depth and table cap as the app
    doc = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "env": env,
           "views": {k: views[k] for k in sorted(views)}, "types": {k: types[k] for k in sorted(types)}}
    return doc, sorted(failed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    ap.add_argument("--profile", help="CLI profile (default: DATABRICKS_HOST / DATABRICKS_TOKEN, as in the pipeline)")
    ap.add_argument("--out", type=Path, default=MAP_PATH)
    a = ap.parse_args()

    from databricks.sdk import WorkspaceClient
    client = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    refs = references(a.env)
    doc, failed = build(client, refs, a.env)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    empty = sorted(k for k, v in doc["views"].items() if not v)
    print(f"Source map for {a.env}: {len(refs)} dataset references, {len(doc['views'])} views mapped, "
          f"{len(doc['types'])} tables typed, {len(failed)} lookups failed"
          + (f" ({', '.join(failed[:10])})" if failed else "")
          + (f", {len(empty)} views read no table ({', '.join(empty[:10])})" if empty else "") + f" -> {a.out}")
    if failed and os.getenv("TF_BUILD"):  # Azure Pipelines: show it as a warning on the run
        print(f"##vso[task.logissue type=warning]Source map: {len(failed)} lookups failed; those views fall back to the Tables API")
    if failed and os.getenv("GITHUB_ACTIONS"):  # GitHub Actions: the same, as a workflow warning
        print(f"::warning::Source map: {len(failed)} lookups failed; those views fall back to the Tables API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
