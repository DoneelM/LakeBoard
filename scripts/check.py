"""Validates every dashboard. CI runs this on each pull request.

    python scripts/check.py --static                          # manifests, SQL rules, page references (no Databricks)
    python scripts/check.py --profile <p> --warehouse <id>    # also runs every dataset with LIMIT 0
    python scripts/check.py --env dev --profile <p> --warehouse <id>   # same, with the dev catalog names

--env picks the catalogs (src/environments.yml). Dashboards switched off for that environment are skipped.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from portal.registry import load_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--profile")
    ap.add_argument("--warehouse")
    ap.add_argument("--env", default="prod", choices=["dev", "test", "prod"])
    args = ap.parse_args()
    boards = load_all(env=args.env)
    failed = 0
    for d in boards.values():
        for e in d.errors:
            print(f"FAIL {d.slug}: {e}")
            failed += 1
        if not d.errors:
            print(f"ok   {d.slug}: {len(d.datasets)} datasets")
    if args.static or failed:
        return 1 if failed else 0

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    from portal.data import bind

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    for d in boards.values():
        if args.env not in d.environments:
            print(f"skip {d.slug}: not enabled in {args.env}")
            continue
        for ds in d.datasets.values():
            params = bind(d, ds, {})  # the same binding the app uses, so defaults such as @week_start resolve
            t0 = time.time()
            r = w.statement_execution.execute_statement(statement=f"SELECT * FROM ({ds.sql}) LIMIT 0", warehouse_id=args.warehouse,
                                                        parameters=params or None, wait_timeout="50s")
            while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
                time.sleep(3)
                r = w.statement_execution.get_statement(r.statement_id)
            if r.status.state != StatementState.SUCCEEDED:
                failed += 1
                print(f"FAIL {d.slug}/{ds.id}: {r.status.error.message if r.status.error else r.status.state}")
            else:
                print(f"ok   {d.slug}/{ds.id} ({time.time() - t0:.0f}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
