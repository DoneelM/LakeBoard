"""Lets the portal app's service principal read what it pre-loads in the background.

Background warming (`warm:` and `auth: app` datasets) runs without a signed-in user, as the app's own service
principal. That principal needs USE CATALOG, USE SCHEMA and SELECT on the views those datasets read. Run this once
per environment after the app is first deployed, and again when a warmed dataset starts reading a new view.

    python scripts/grant_app_access.py --env prod --profile <profile> --warehouse <id>            # shows the grants
    python scripts/grant_app_access.py --env prod --profile <profile> --warehouse <id> --apply    # runs them

Grants survive view changes made with ALTER VIEW. A view that is dropped and recreated (CREATE OR REPLACE VIEW)
loses them; run this again.

Metadata only: the freshness label ("source unchanged" / "newer data available") asks Unity Catalog, as the same
service principal, when each dataset's source tables last changed (Tables API, following views to the tables they
read). That needs BROWSE on each catalog those views and tables live in (the catalog the dashboards read, plus any
catalog their views read from). BROWSE shows metadata only (names, types, last-modified time; not what a view reads, which comes
from the deploy-time map, scripts/build_sources_map.py), never rows, and needs no USE CATALOG or USE SCHEMA. The script finds the catalogs by following the views with your --profile, so run
it as someone who can see them. Without the grant the label just leaves the cue out.
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from portal.registry import TABLE_RE, load_all, strip_sql_comments_and_strings, tables_in  # noqa: E402
from portal.sources import lookup, resolve  # noqa: E402
from portal.settings import USAGE_TABLES  # noqa: E402

# App names per environment, as in databricks.yml (app_name). Use --app if you renamed them.
APPS = {"dev": "lakeboard-dev", "test": "lakeboard-test", "prod": "lakeboard"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, choices=sorted(APPS))
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--app", help="app name (default: lakeboard, lakeboard-dev or lakeboard-test)")
    ap.add_argument("--apply", action="store_true", help="run the grants (default: only print them)")
    a = ap.parse_args()
    app_name = a.app or APPS[a.env]

    tables, refs = set(), set()
    for d in load_all(env=a.env).values():
        if d.errors or a.env not in d.environments:
            continue
        for ds in d.datasets.values():
            refs.update(tables_in(ds.sql))  # every dataset's source time is looked up, so all of them count here
            if ds.warm or ds.auth == "app":
                for first, rest in TABLE_RE.findall(strip_sql_comments_and_strings(ds.sql)):
                    parts = [first] + [x for x in rest.split(".") if x]
                    if len(parts) == 3:
                        tables.add(tuple(parts))
    usage_table = USAGE_TABLES.get(a.env)
    if not tables and not usage_table and not refs:
        print("No datasets and no usage table in this environment; nothing to grant.")
        return 0

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    w = WorkspaceClient(profile=a.profile)
    try:
        app = w.apps.get(app_name)
    except Exception as e:
        raise SystemExit(f"App {app_name} was not found in this workspace. Deploy it first (docs/PROMOTION.md). {str(e)[:120]}")
    principal = app.service_principal_client_id
    if not principal or not re.fullmatch(r"[0-9a-f-]{36}", principal):
        raise SystemExit(f"Could not read the service principal of app {app_name}")
    print(f"App {app_name}: service principal {app.service_principal_name} ({principal})")

    scopes = set(tables) | ({tuple(usage_table.split("."))} if usage_table else set())
    statements = [f"GRANT USE CATALOG ON CATALOG {c} TO `{principal}`" for c in sorted({t[0] for t in scopes})]
    statements += [f"GRANT USE SCHEMA ON SCHEMA {c}.{s} TO `{principal}`" for c, s in sorted({t[:2] for t in scopes})]
    statements += [f"GRANT SELECT ON TABLE {'.'.join(t)} TO `{principal}`" for t in sorted(tables)]
    if usage_table:  # the app writes page views here
        statements.append(f"GRANT SELECT, MODIFY ON TABLE {usage_table} TO `{principal}`")

    # Metadata only, for the freshness label: BROWSE on every catalog the dataset views and their source tables are in.
    catalogs, unresolved = set(), []
    # Every catalog holding a view to follow or a table to classify. Foreign (federated) and external tables are never
    # timed, but the app still has to see their type: one it can't see is unknown, and that hides the cue.
    for ref in sorted(refs):
        seen: set[str] = set()
        for t in resolve(w, ref, seen):
            if t["updated_at"] is None and t["kind"] != "static" and lookup(w, t["name"])[0] == "unknown":
                unresolved.append(t["name"])
        catalogs.update(n.split(".")[0] for n in seen if lookup(w, n)[0] != "unknown")
    metadata = [f"GRANT BROWSE ON CATALOG {c} TO `{principal}`" for c in sorted(catalogs)]
    if not a.apply:
        print("-- Data access (SELECT) for warmed and auth: app datasets, and the usage table:")
        for sql in statements:
            print(sql + ";")
        if metadata:
            print("\n-- Metadata only (freshness label: when source tables last changed). BROWSE gives no access to rows:")
            for sql in metadata:
                print(sql + ";")
    if unresolved:
        print(f"\nNote: no last-change time for {len(sorted(set(unresolved)))} table(s) or view(s) (your profile can't read "
              f"it, or a view reads no table), so a catalog may be missing above: {', '.join(sorted(set(unresolved))[:10])}")
    statements += metadata
    failed = 0
    for sql in statements if a.apply else []:
        r = w.statement_execution.execute_statement(statement=sql, warehouse_id=a.warehouse, wait_timeout="50s")
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = w.statement_execution.get_statement(r.statement_id)
        ok = r.status.state == StatementState.SUCCEEDED
        failed += not ok
        print(("ok   " if ok else "FAIL ") + sql + ("" if ok else f"\n     {r.status.error.message[:300] if r.status.error else r.status.state}"))
    if not a.apply:
        print("\nNothing was changed. Add --apply to run these.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
