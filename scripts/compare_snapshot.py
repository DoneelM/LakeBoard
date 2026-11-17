"""Reconciles a dataset's new SQL with the snapshot an artifact import saved (snapshots/<id>.json).

    python scripts/compare_snapshot.py --slug <slug> --dataset <id> --profile <p> --warehouse <id>
        [--env dev] [--params k=v ...] [--keys col,col] [--tolerance 0.005]

Runs sql/<id>.sql the way the portal does (catalog names for --env, parameters from dashboard.yml defaults,
overridden by --params), then compares with the snapshot: column set, row count, rows only on one side, and
numeric differences per key beyond the relative tolerance. The snapshot is the artifact's data on the day it was
saved, so recent rows may differ because the data moved on. Exit 0 when it reconciles, 1 on a mismatch, 2 when
it can't run.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from portal.registry import PARAM_RE, strip_sql_comments_and_strings  # noqa: E402
from portal.settings import localise_sql, resolve_default  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
from import_artifact import sql_problems  # noqa: E402

DASHBOARDS = REPO / "src" / "dashboards"
MAX_SHOWN = 15


def number(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).strip().replace(",", "")) if str(v).strip() else None
    except ValueError:
        return None
    return f if f is not None and math.isfinite(f) else None


def norm(v) -> str:
    """Text form for matching keys and comparing non-numbers: blank and null are the same; dates lose the time."""
    if v is None:
        return ""
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?(?:Z|[+-]00:?00)?", s)
    if m:
        return m.group(1)
    n = number(s)
    if n is not None and re.fullmatch(r"-?[\d,]*\.?\d+(?:[eE][-+]?\d+)?", s):
        return repr(float(n))
    return s


def same(a, b, tolerance: float) -> tuple[bool, float | None]:
    """(equal, relative difference when both are numbers)."""
    x, y = number(a), number(b)
    if x is not None and y is not None:
        diff = abs(x - y)
        rel = diff / max(abs(x), abs(y)) if max(abs(x), abs(y)) else 0.0
        return diff <= 1e-9 or rel <= tolerance, rel
    return norm(a) == norm(b), None


def compare(snapshot: dict, live: dict, keys: list[str] | None = None, tolerance: float = 0.005) -> dict:
    """Compares two {columns, rows} tables. Column names match without regard to case."""
    s_cols, l_cols = list(snapshot["columns"]), list(live["columns"])
    s_idx = {c.lower(): i for i, c in enumerate(s_cols)}
    l_idx = {c.lower(): i for i, c in enumerate(l_cols)}
    common = [c for c in s_cols if c.lower() in l_idx]
    out = {
        "only_snapshot_columns": [c for c in s_cols if c.lower() not in l_idx],
        "only_live_columns": [c for c in l_cols if c.lower() not in s_idx],
        "column_order_differs": [c.lower() for c in s_cols if c.lower() in l_idx] != [c.lower() for c in l_cols if c.lower() in s_idx],
        "snapshot_rows": len(snapshot["rows"]), "live_rows": len(live["rows"]),
        "keys": [], "only_snapshot": [], "only_live": [], "differences": [], "duplicate_keys": 0, "matched": 0,
    }

    def val(row, idx, col):
        i = idx[col.lower()]
        return row[i] if i < len(row) else None

    if keys is None:  # the text columns, if together they identify a row on both sides
        keys = [c for c in common if not all(number(val(r, s_idx, c)) is not None or val(r, s_idx, c) in (None, "")
                                             for r in snapshot["rows"])]
    keys = [k for k in keys if k.lower() in s_idx and k.lower() in l_idx]

    def index(rows, idx):
        d: dict[tuple, list] = {}
        for r in rows:
            d.setdefault(tuple(norm(val(r, idx, k)) for k in keys), []).append(r)
        return d

    s_map, l_map = index(snapshot["rows"], s_idx), index(live["rows"], l_idx)
    if keys and all(len(v) == 1 for v in s_map.values()) and all(len(v) == 1 for v in l_map.values()):
        out["keys"] = keys
        values = [c for c in common if c not in keys]
        for k, (srow,) in s_map.items():
            if k not in l_map:
                out["only_snapshot"].append(dict(zip(keys, k)))
                continue
            lrow = l_map[k][0]
            out["matched"] += 1
            for c in values:
                ok, rel = same(val(srow, s_idx, c), val(lrow, l_idx, c), tolerance)
                if not ok:
                    out["differences"].append({"key": dict(zip(keys, k)), "column": c, "snapshot": val(srow, s_idx, c),
                                               "live": val(lrow, l_idx, c), "relative": rel})
        out["only_live"] = [dict(zip(keys, k)) for k in l_map if k not in s_map]
    else:  # no usable key: compare whole rows as multisets (numbers rounded to the tolerance's precision)
        out["duplicate_keys"] = sum(len(v) - 1 for v in s_map.values()) if keys else 0
        digits = max(0, int(-math.log10(tolerance)) + 1) if tolerance > 0 else 9

        def rowkey(r, idx):
            vals = []
            for c in common:
                v = val(r, idx, c)
                n = number(v)
                vals.append(f"{n:.{digits}g}" if n is not None else norm(v))
            return tuple(vals)

        s_rows: dict[tuple, int] = {}
        for r in snapshot["rows"]:
            s_rows[rowkey(r, s_idx)] = s_rows.get(rowkey(r, s_idx), 0) + 1
        l_rows: dict[tuple, int] = {}
        for r in live["rows"]:
            l_rows[rowkey(r, l_idx)] = l_rows.get(rowkey(r, l_idx), 0) + 1
        for k, n in s_rows.items():
            m = min(n, l_rows.get(k, 0))
            out["matched"] += m
            out["only_snapshot"] += [dict(zip(common, k))] * (n - m)
        for k, n in l_rows.items():
            out["only_live"] += [dict(zip(common, k))] * (n - min(n, s_rows.get(k, 0)))
    out["ok"] = not (out["only_snapshot_columns"] or out["only_live_columns"] or out["only_snapshot"]
                     or out["only_live"] or out["differences"]) and out["snapshot_rows"] == out["live_rows"]
    return out


def report(result: dict, slug: str, ds: str, saved: str, tolerance: float) -> list[str]:
    lines = [f"Reconciliation of {slug}/{ds}: snapshot saved {saved or 'at an unknown time'} vs live now.",
             "The data has moved on since the snapshot, so recent periods can differ for that reason alone."]
    if result["only_snapshot_columns"] or result["only_live_columns"]:
        lines.append(f"Columns only in the snapshot: {result['only_snapshot_columns'] or 'none'}; "
                     f"only in the live result: {result['only_live_columns'] or 'none'} (the page reads the snapshot's names)")
    else:
        lines.append("Columns: same set" + (" (order differs; the page reads columns by name)" if result["column_order_differs"] else ""))
    lines.append(f"Rows: snapshot {result['snapshot_rows']}, live {result['live_rows']}, matched {result['matched']}")
    lines.append(f"Matched on: {', '.join(result['keys'])}" if result["keys"] else
                 "Matched whole rows (no key column identifies each row; pass --keys)")
    for label, items in (("Only in the snapshot", result["only_snapshot"]), ("Only live", result["only_live"])):
        if items:
            lines.append(f"{label}: {len(items)} rows")
            lines += [f"  {json.dumps(x, ensure_ascii=False)}" for x in items[:MAX_SHOWN]]
    if result["differences"]:
        lines.append(f"Values outside the {tolerance:.2%} tolerance: {len(result['differences'])}")
        for d in result["differences"][:MAX_SHOWN]:
            rel = f" ({d['relative']:.2%})" if d["relative"] is not None else ""
            lines.append(f"  {json.dumps(d['key'], ensure_ascii=False)} {d['column']}: snapshot {d['snapshot']}, live {d['live']}{rel}")
    lines.append("RECONCILED" if result["ok"] else "MISMATCH")
    return lines


def run_query(profile: str | None, warehouse: str, sql: str, params: list[dict]) -> dict:
    """Runs one statement like the portal does (portal/data.py run_sql), all rows."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import Disposition, Format, StatementParameterListItem, StatementState

    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    items = [StatementParameterListItem(name=p["name"], type=p["type"], value=p["value"]) for p in params]
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse, parameters=items or None,
                                                wait_timeout="30s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error.message if r.status.error else str(r.status.state))
    rows = list((r.result and r.result.data_array) or [])
    chunk = r.result
    while chunk is not None and chunk.next_chunk_index is not None:
        chunk = w.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk.next_chunk_index)
        rows.extend(chunk.data_array or [])
    return {"columns": [c.name for c in r.manifest.schema.columns], "rows": rows}


def load(slug: str, ds: str, env: str, overrides: dict[str, str], root: Path = DASHBOARDS):
    """(localised SQL, parameters, snapshot, snapshot date) for one dataset. Raises SystemExit with a reason."""
    folder = root / slug
    manifest = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8")) or {}
    spec = (manifest.get("datasets") or {}).get(ds)
    if not spec:
        raise SystemExit(f"{slug} has no dataset {ds!r}")
    sql = (folder / spec["sql"]).read_text(encoding="utf-8").strip().rstrip(";")
    problems = sql_problems(sql)
    if problems:
        raise SystemExit(f"sql/{ds}.sql can't run yet: " + "; ".join(problems))
    snap_path = folder / (spec.get("snapshot") or f"snapshots/{ds}.json")
    if not snap_path.is_file():
        raise SystemExit(f"{snap_path} not found; import the artifact again with --blobs")
    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    saved = ""
    info = snap_path.parent / "_import.json"
    if info.is_file():
        saved = (json.loads(info.read_text(encoding="utf-8")).get(ds) or {}).get("saved", "")
    declared = manifest.get("params") or {}
    params = []
    for name in sorted(set(PARAM_RE.findall(strip_sql_comments_and_strings(sql)))):
        pspec = declared.get(name) or {}
        value = overrides.get(name) or resolve_default(pspec.get("default"))
        params.append({"name": name, "type": str(pspec.get("type", "STRING")).upper(),
                       "value": None if value in (None, "") else str(value)})
    unknown = sorted(set(overrides) - {p["name"] for p in params})
    if unknown:
        raise SystemExit(f"--params {unknown} are not used by sql/{ds}.sql")
    return localise_sql(sql, env), params, snapshot, saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--profile", required=True, help="Databricks CLI profile")
    ap.add_argument("--warehouse", required=True, help="SQL warehouse id")
    ap.add_argument("--env", default="prod", choices=["dev", "test", "prod"], help="catalog names to use")
    ap.add_argument("--params", nargs="*", default=[], metavar="NAME=VALUE",
                    help="parameter values; use the artifact's values on the day of the snapshot")
    ap.add_argument("--keys", help="comma-separated columns that identify a row (default: the text columns)")
    ap.add_argument("--tolerance", type=float, default=0.005, help="relative difference allowed for numbers")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    overrides = {}
    for kv in a.params:
        if "=" not in kv:
            print(f"error: --params takes NAME=VALUE, not {kv!r}", file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        overrides[k.strip()] = v
    try:
        sql, params, snapshot, saved = load(a.slug, a.dataset, a.env, overrides)
        live = run_query(a.profile, a.warehouse, sql, params)
    except SystemExit as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # query failed
        print(f"error: the query failed: {e}", file=sys.stderr)
        return 2
    keys = [k.strip() for k in a.keys.split(",") if k.strip()] if a.keys else None
    result = compare(snapshot, live, keys, a.tolerance)
    if params:
        print("Parameters: " + ", ".join(f"{p['name']}={p['value']}" for p in params))
    print("\n".join(report(result, a.slug, a.dataset, saved, a.tolerance)))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
