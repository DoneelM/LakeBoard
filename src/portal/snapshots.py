"""Snapshot preview for `todo` datasets (decision 0011).

A dataset imported from a Claude artifact can say `todo: true` (not connected to Databricks yet) and
`snapshot: snapshots/<id>.json`, the rows the artifact showed. The snapshot folder is gitignored: it holds business
data and must never be committed or deployed. Only a local run with PORTAL_PREVIEW_SNAPSHOTS=1 serves it, so the
person importing the page can see it working before the SQL is written. A deployed app never does.
"""
from __future__ import annotations

import json
import os

from .registry import Dashboard, Dataset
from .settings import is_local_run

MAX_SNAPSHOT_BYTES = 20_000_000


def preview_enabled(environ=None) -> bool:
    """Local run (PORTAL_LOCAL_PROFILE, not inside Databricks Apps) and PORTAL_PREVIEW_SNAPSHOTS=1."""
    environ = os.environ if environ is None else environ
    return is_local_run(environ) and environ.get("PORTAL_PREVIEW_SNAPSHOTS", "") == "1"


def _text(v):
    """The same shape as SQL results: every value a string, or None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def load(board: Dashboard, ds: Dataset) -> dict:
    """{columns, rows, cut} from snapshots/<id>.json: {"columns": [...], "rows": [[...]]} or a list of row objects."""
    if not ds.todo or not ds.snapshot:
        raise FileNotFoundError("this dataset has no snapshot")
    root = (board.path / "snapshots").resolve()
    path = (board.path / ds.snapshot).resolve()
    if path.parent != root or path.suffix != ".json":  # the registry already checks the name; belt and braces
        raise FileNotFoundError("snapshot must be in the dashboard's snapshots/ folder")
    if not path.is_file():
        raise FileNotFoundError(f"{ds.snapshot} not found in {board.slug}/")
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"{ds.snapshot} is larger than {MAX_SNAPSHOT_BYTES // 1_000_000} MB")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("columns"), list) and isinstance(raw.get("rows"), list):
        columns = [str(c) for c in raw["columns"]]
        rows = []
        for r in raw["rows"]:
            if not isinstance(r, list) or len(r) != len(columns):
                raise ValueError(f"{ds.snapshot}: every row must be a list of {len(columns)} values")
            rows.append([_text(v) for v in r])
    elif isinstance(raw, list) and all(isinstance(r, dict) for r in raw):
        columns = []
        for r in raw:
            columns += [str(k) for k in r if str(k) not in columns]
        rows = [[_text(r.get(c)) for c in columns] for r in raw]
    else:
        raise ValueError(f'{ds.snapshot} must be {{"columns": [...], "rows": [[...]]}} or a list of row objects')
    return {"columns": columns, "rows": rows, "cut": False}
