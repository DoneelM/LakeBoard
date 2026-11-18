"""Turns a Claude Dashboard artifact (read with ArtifactData into a folder) into a LakeBoard draft dashboard.

    python scripts/import_artifact.py --bundle <out_dir> --slug <slug> [--blobs <dir>] [--force]

<out_dir> holds what ArtifactData `list` wrote for the collections `dash`, `datasets` and `files`:
    dash/meta.json, dash/params.json, datasets/<id>.json, files/<name>.json ({"text": ...})
--blobs is a folder with the attached data files, named by asset id (the 32 hex characters in the dataset's
`/_blob/<id>` url, with or without an extension) or by the file name the dataset gives.

Writes src/dashboards/<slug>/ (dashboard.yml, index.html, assets/*, sql/*.sql, snapshots/*.json, IMPORT.md) and
nothing else. The artifact's text and data are treated as data: nothing in them is run. The procedure around this
script is .claude/skills/import-claude-dashboard/SKILL.md. Exit code 2 only when the bundle cannot be read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from portal import registry  # noqa: E402
from portal.registry import (  # noqa: E402
    DATASET_RE, FORBIDDEN, PARAM_RE, SLUG_RE, strip_sql_comments_and_strings, table_errors,
)

# What a page: artifact dashboard may keep in assets/ (the registry's rules; fallbacks for an older registry)
ASSET_NAME_RE = getattr(registry, "ASSET_NAME_RE", re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$"))
ASSET_TYPES = set(getattr(registry, "ASSET_TYPES", {".js": 0, ".css": 0, ".png": 0, ".jpg": 0, ".svg": 0}))
SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

DASHBOARDS = REPO / "src" / "dashboards"
STUB_MARK = "-- TODO: write the SQL for this dataset"
BLANK_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")
QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.|'')*)'")
DATE_PATTERN_RE = re.compile(r"\\d\{4\}-\\d\{2\}-\\d\{2\}|\[0-9\]\{4\}-")
DATE_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
UC_TABLE_RE = re.compile(r"`?\b([A-Za-z_][\w]*)`?\.`?([A-Za-z_][\w]*)`?\.`?([A-Za-z_][\w]*)\b`?")
SQL_ARG_NAMES = ("query", "statement", "sql")
# What the portal's `dash` provides: read from src/static/dash.js; this list if that can't be read.
LAKEBOARD_DASH = {"data", "onData", "params", "setParams", "resetParams", "allowed", "refresh", "genieContext", "colors"}
_SCALE = ("xs", "sm", "md", "lg", "xl")
# Tokens an artifact page may rely on until docs/decisions/0011 lists them; the theme in src/static/*.css is added.
FALLBACK_TOKENS = {
    *(f"--color-{n}" for n in ("fg", "fg-muted", "bg", "panel", "border-line", "ok", "warn", "bad")),
    *(f"--cds-font-size-{n}" for n in ("caption", "body", "heading", "title")),
    "--cds-font-weight-medium", "--cds-radius",
    *(f"--cds-gap-{n}" for n in _SCALE), *(f"--cds-pad-{n}" for n in _SCALE),
    *(f"--cds-chart-{n}" for n in ("muted", "status-critical", "grid", "axis", "reference")),
    "--cds-surface-popover", "--cds-border", "--cds-shadow-popover", "--cds-text-secondary", "--cds-dur-slow",
    "--cds-ease-out",
}
UNSUPPORTED = [  # (label, pattern) for things a portal page cannot do
    ("external URL", re.compile(r"""https?://[^\s"'<>)]+|(?<=["'(])//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s"'<>)]*""")),
    ("fetch()", re.compile(r"\bfetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("WebSocket", re.compile(r"\bWebSocket\b")),
    ("<iframe>", re.compile(r"<iframe\b", re.I)),
    ("<form>", re.compile(r"<form\b", re.I)),
]
HARMLESS_URL = re.compile(r"//www\.w3\.org/")  # SVG/XHTML namespaces are not requests


class BundleError(Exception):
    """The bundle can't be read (missing folder, broken JSON). The only reason to exit non-zero."""


@dataclass
class DatasetResult:
    id: str
    title: str
    description: str
    kind: str  # converted | needs-sql | unsupported-connector | check-failed
    detail: str = ""
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: int | None = None
    snapshot: bool = False
    tables: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    updated: str = ""


# ---------------------------------------------------------------- reading


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BundleError(f"{path}: {e}") from e


def read_collection(bundle: Path, name: str) -> dict[str, dict]:
    folder = bundle / name
    if not folder.is_dir():
        return {}
    out = {}
    for p in sorted(folder.glob("*.json")):
        doc = read_json(p)
        if not isinstance(doc, dict):
            raise BundleError(f"{p}: expected a JSON object (one document, fields at top level)")
        out[p.name[:-5]] = doc
    return out


def one_line(text) -> str:
    return " ".join(str(text or "").split())


# ---------------------------------------------------------------- params


def infer_type(default, rule: dict | None) -> tuple[str, list[str]]:
    """LakeBoard type for one artifact parameter, plus the rule parts LakeBoard does not enforce."""
    rule = rule if isinstance(rule, dict) else {}
    unenforced = []
    rtype = str(rule.get("type") or "").lower()
    fmt = str(rule.get("format") or "").lower()
    pattern = str(rule.get("pattern") or "")
    ptype = ""
    if fmt == "date" or (pattern and DATE_PATTERN_RE.search(pattern)):
        ptype = "DATE"
    elif fmt == "date-time":
        ptype = "TIMESTAMP"
    elif rtype == "integer":
        ptype = "INT"
    elif rtype == "number":
        ptype = "DOUBLE"
    elif rtype == "boolean":
        ptype = "BOOLEAN"
    if not ptype:
        if isinstance(default, bool):
            ptype = "BOOLEAN"
        elif isinstance(default, int):
            ptype = "INT"
        elif isinstance(default, float):
            ptype = "DOUBLE"
        elif isinstance(default, str) and DATE_VALUE_RE.match(default):
            ptype = "DATE"
        elif isinstance(default, str) and TIMESTAMP_VALUE_RE.match(default):
            ptype = "TIMESTAMP"
        else:
            ptype = "STRING"
    for key in ("enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
                "const", "multipleOf"):
        if key in rule:
            unenforced.append(f"{key} {json.dumps(rule[key], ensure_ascii=False)}")
    if pattern and ptype not in ("DATE", "TIMESTAMP"):
        unenforced.append(f"pattern {json.dumps(pattern)}")
    return ptype, unenforced


def build_params(defaults: dict, rules: dict[str, dict], used: set[str], warnings: list[str]) -> dict[str, dict]:
    params = {}
    for name in sorted(set(defaults) | set(rules) | used):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            warnings.append(f"parameter {name!r} is not a valid SQL parameter name; rename it in the SQL and the page")
            continue
        default = defaults.get(name)
        ptype, unenforced = infer_type(default, rules.get(name))
        spec: dict = {"type": ptype}
        if default is not None and default != "":
            if isinstance(default, str) and default.startswith("@"):
                warnings.append(f"parameter {name}: default {default!r} left out (LakeBoard reserves @ for date tokens)")
            elif isinstance(default, (str, int, float, bool)):
                spec["default"] = default
            else:
                warnings.append(f"parameter {name}: default {json.dumps(default)} is not a single value; left out")
        if name not in defaults:
            warnings.append(f"parameter {name} is used in SQL but has no default in dash/params; added with none")
        spec["unenforced"] = unenforced
        params[name] = spec
    return params


# ---------------------------------------------------------------- SQL


def to_lakeboard_sql(sql: str) -> tuple[str, list[str], list[str], list[str]]:
    """Replaces '{{x}}' and {{x}} with :x. Returns (sql, parameter names, notes, blanks that were not quoted)."""
    notes: list[str] = []

    def quoted(m: re.Match) -> str:
        inner = m.group(1)
        blanks = BLANK_RE.findall(inner)
        if not blanks:
            return m.group(0)
        if BLANK_RE.fullmatch(inner.strip()) and inner == inner.strip():
            return f":{blanks[0]}"
        parts, pos = [], 0
        for b in BLANK_RE.finditer(inner):
            if b.start() > pos:
                parts.append("'" + inner[pos:b.start()] + "'")
            parts.append(f":{b.group(1)}")
            pos = b.end()
        if pos < len(inner):
            parts.append("'" + inner[pos:] + "'")
        notes.append(f"the literal '{inner}' became concat({', '.join(parts)}); check it")
        return "concat(" + ", ".join(parts) + ")"

    out = QUOTED_RE.sub(quoted, sql)
    bare = sorted(set(BLANK_RE.findall(out)))
    out = BLANK_RE.sub(lambda m: f":{m.group(1)}", out)
    names = sorted(set(BLANK_RE.findall(sql)))
    return out.strip().rstrip(";").rstrip(), names, notes, bare


def sql_problems(sql: str) -> list[str]:
    """The registry's rules for one dataset's SQL (read-only, one statement, allowed catalogs)."""
    body = strip_sql_comments_and_strings(sql)
    problems = []
    if not re.match(r"\s*(WITH|SELECT)\b", body, re.IGNORECASE):
        problems.append("SQL must start with SELECT or WITH")
    if ";" in body:
        problems.append("SQL must be a single statement")
    bad = FORBIDDEN.search(body)
    if bad:
        problems.append(f"SQL contains {bad.group(1).upper()}")
    return problems + table_errors(body)


def find_sql_arg(source: dict, langs: dict) -> tuple[str | None, str | None]:
    """(arg name, SQL text) of a live query's SQL, or (None, None)."""
    args = source.get("args") if isinstance(source.get("args"), dict) else None
    if args is None:  # older form: the SQL sits on the source itself
        args = {k: v for k, v in source.items() if k in SQL_ARG_NAMES}
    for name, lang in (langs or {}).items():
        if str(lang).lower() == "sql" and isinstance(args.get(name), str):
            return name, args[name]
    for name in SQL_ARG_NAMES:
        if isinstance(args.get(name), str):
            return name, args[name]
    return None, None


NOT_TABLES = ("csv", "json", "tsv", "txt", "html", "js", "css", "md", "com", "net", "org", "io")
# A bare name listed right after a qualified one ("cat.schema.a_vw, b_vw and c_vw"): it takes that catalog.schema
LIST_TAIL_RE = re.compile(r"\s*(?:,\s*(?:and\s+|&\s*)?|\s+and\s+|\s*&\s*|\s*/\s*)`?([A-Za-z_]\w*)`?(?![\w.`])")


def tables_named(text: str) -> list[str]:
    """catalog.schema.table names in a description, plus bare names listed after one (same catalog.schema).
    Bare names count only with a '_' or a digit in them, so ordinary words after "and" are not taken for tables."""
    text = text or ""
    found: list[str] = []

    def add(name: str) -> None:
        if name not in found:
            found.append(name)

    for m in UC_TABLE_RE.finditer(text):
        a, b, c = m.groups()
        if c.lower() in NOT_TABLES:
            continue
        add(f"{a}.{b}.{c}")
        pos = m.end()
        while True:
            t = LIST_TAIL_RE.match(text, pos)
            if not t or not re.search(r"[_\d]", t.group(1)) or text[t.end(1):t.end(1) + 1] == ".":
                break
            add(f"{a}.{b}.{t.group(1)}")
            pos = t.end()
    return found


# ---------------------------------------------------------------- SQL kept in dash/* documents (refresh routines)

_SQL_START = r"^[ \t]*(?:SELECT\b|WITH\s+(?:RECURSIVE\s+)?`?\w+`?\s*(?:\([^)]*\)\s*)?AS\s*\()"
# Upper-case keywords first, so an instruction line such as "With this SQL..." is not taken for the query
SQL_START_RES = (re.compile(_SQL_START, re.MULTILINE), re.compile(_SQL_START, re.MULTILINE | re.IGNORECASE))
SQL_WORDS = {"SELECT", "WITH", "FROM", "WHERE", "GROUP", "ORDER", "HAVING", "JOIN", "LEFT", "RIGHT", "INNER", "FULL",
             "CROSS", "UNION", "LIMIT", "AND", "OR", "ON", "QUALIFY", "WINDOW", "EXCEPT", "INTERSECT", "AS", "CASE",
             "WHEN", "THEN", "ELSE", "END", "LATERAL", "PIVOT", "UNPIVOT", "USING", "NOT", "IN", "IS", "BETWEEN"}


def extract_sql(text: str) -> str | None:
    """The SQL in a refresh routine's text: from the first line starting with SELECT/WITH, up to a top-level ';'
    or a trailing paragraph of prose. The words before it (instructions to the scheduled task) are not used."""
    m = SQL_START_RES[0].search(text or "") or SQL_START_RES[1].search(text or "")
    if not m:
        return None
    body = text[m.start():].lstrip()
    quote = None
    for i, ch in enumerate(body):  # cut at the first ';' outside quotes
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == ";":
            body = body[:i]
            break
    paras = re.split(r"\n\s*\n", body.strip())
    while len(paras) > 1:
        first = re.match(r"\s*([A-Za-z]+)", paras[-1])
        if first and first.group(1).upper() not in SQL_WORDS:
            paras.pop()  # prose such as "Return the result as CSV."
        else:
            break
    return "\n\n".join(paras).strip() or None


def routine_sql(dash: dict[str, dict], dataset_ids: set[str], warnings: list[str]) -> dict[str, tuple[str, str]]:
    """{dataset id: (document name, SQL)} from every dash/* document except meta and params: any text value under a
    key that is a dataset id and holds a SELECT/WITH. The text is data; nothing in it is followed."""
    found: dict[str, tuple[str, str]] = {}

    def walk(doc_name: str, node) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if isinstance(value, dict):
                walk(doc_name, value)
            elif isinstance(value, str) and key in dataset_ids:
                sql = extract_sql(value)
                if sql and key not in found:
                    found[key] = (doc_name, sql)
            elif isinstance(value, str) and extract_sql(value) and DATASET_RE.match(str(key)):
                warnings.append(f"dash/{doc_name}: SQL under {key!r}, which is not a dataset of the artifact; not used")

    for doc_name, doc in sorted(dash.items()):
        if doc_name not in ("meta", "params"):
            walk(doc_name, doc)
    return found


# ---------------------------------------------------------------- file datasets


def cell(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def read_delimited(text: str, sep: str) -> tuple[list[str], list[list]]:
    """Header + rows, split on the separator only (no quoting rules), like the artifact host does."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return [], []
    columns = lines[0].split(sep)
    rows = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cells = ln.split(sep)
        rows.append(fit(cells, len(columns)))
    return columns, rows


def fit(row: list, n: int) -> list:
    """Exactly n values (the portal's snapshot reader requires it)."""
    return (list(row) + [None] * n)[:n]


def read_json_rows(text: str) -> tuple[list[str], list[list]]:
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("columns"), list) and isinstance(data.get("rows"), list):
        cols = [str(c) for c in data["columns"]]
        return cols, [fit([cell(v) for v in r], len(cols)) for r in data["rows"] if isinstance(r, list)]
    if isinstance(data, dict):  # {"rows": [...]} / {"data": [...]}
        for key in ("rows", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("expected a list of rows")
    if all(isinstance(r, dict) for r in data):
        columns: list[str] = []
        for r in data:
            columns += [k for k in r if k not in columns]
        return columns, [[cell(r.get(c)) for c in columns] for r in data]
    if all(isinstance(r, list) for r in data) and data:
        cols = [str(c) for c in data[0]]
        return cols, [fit([cell(v) for v in r], len(cols)) for r in data[1:]]
    raise ValueError("rows must be objects or arrays")


def find_blob(blobs: Path | None, url: str, name: str) -> Path | None:
    if not blobs or not blobs.is_dir():
        return None
    m = re.search(r"([0-9a-f]{32})", url or "")
    asset = m.group(1) if m else None
    files = sorted(p for p in blobs.iterdir() if p.is_file())
    for p in files:
        if asset and (p.name == asset or p.stem == asset):
            return p
    for p in files:
        if name and p.name == name:
            return p
    return None


def snapshot_from(path: Path, fmt: str, name: str) -> tuple[list[str], list[list]]:
    fmt = (fmt or Path(name or path.name).suffix.lstrip(".") or "csv").lower()
    text = path.read_text(encoding="utf-8-sig")
    if fmt == "csv":
        return read_delimited(text, ",")
    if fmt == "tsv":
        return read_delimited(text, "\t")
    if fmt == "json":
        return read_json_rows(text)
    raise ValueError(f"format {fmt!r} is not a table")


# ---------------------------------------------------------------- page scan


def guaranteed_tokens() -> set[str]:
    tokens = set(FALLBACK_TOKENS)
    for record in (REPO / "docs" / "decisions").glob("0011-*.md"):
        tokens |= set(re.findall(r"`(--[a-z0-9-]+)`", record.read_text(encoding="utf-8")))
    for css in (REPO / "src" / "static").glob("*.css"):
        tokens |= set(re.findall(r"(?:^|[;{\s])(--[A-Za-z0-9-]+)\s*:", css.read_text(encoding="utf-8")))
    return tokens


def portal_dash() -> set[str]:
    """The members of the portal's `dash` object (the keys of `const dash = {` in src/static/dash.js)."""
    try:
        js = (REPO / "src" / "static" / "dash.js").read_text(encoding="utf-8")
        body = js[js.index("const dash = {"):js.index("window.dash = dash")]
    except (OSError, ValueError):
        return set(LAKEBOARD_DASH)
    return set(re.findall(r"^ {4}([A-Za-z_]\w*)\s*(?:\(|:)", body, re.M)) or set(LAKEBOARD_DASH)


def scan_page(page: str, assets: dict[str, str]) -> dict:
    texts = {"index.html": page, **assets}
    every = "\n".join(texts.values())
    dash_calls: dict[str, int] = {}
    for fn in re.findall(r"\bdash\.([A-Za-z_]\w*)", every):
        dash_calls[fn] = dash_calls.get(fn, 0) + 1
    unsupported = []
    for fname, text in texts.items():
        for label, rx in UNSUPPORTED:
            for m in rx.finditer(text):
                if label == "external URL" and HARMLESS_URL.search(m.group(0)):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                unsupported.append(f"{label} in {fname} line {line}: {m.group(0)[:80]}")
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", every))  # CSS, inline style="--x: …", cssText strings
    defined |= set(re.findall(r"setProperty\(\s*['\"`](--[A-Za-z0-9-]+)", every))  # el.style.setProperty('--x', v)
    defined |= set(re.findall(r"['\"](--[A-Za-z0-9-]+)['\"]\s*:", every))  # style objects {'--x': v}
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9-]+)", every))
    ok = guaranteed_tokens()
    provided = portal_dash()
    refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"'#?]+)""", page, re.I)
    local_refs = [r for r in refs if not re.match(r"^(?:[a-z]+:|//|/)", r, re.I)]
    return {
        "dash": dict(sorted(dash_calls.items())),
        "not_in_portal": sorted(f for f in dash_calls if f not in provided),
        "loader": dash_calls.get("loader", 0),
        "data_draw": len(re.findall(r"\bdata-draw\b", page)),
        "meta": sorted(set(re.findall(r"""<meta[^>]+name\s*=\s*["'](dash-[\w-]+)""", page, re.I))),
        "assets": sorted(assets),
        "missing_assets": sorted({r for r in local_refs if r not in assets and r.lstrip("./") not in assets}),
        "unreferenced_assets": sorted(a for a in assets if not any(r.lstrip("./") == a for r in local_refs)),
        "unsupported": unsupported,
        "custom_tokens": sorted(defined & used),
        "unknown_tokens": sorted(t for t in used if t not in defined and t not in ok),
        "datasets_read": sorted(set(re.findall(r"dash\.(?:data|refresh|loader)\(\s*['\"]([A-Za-z0-9_-]+)['\"]", every))),
        "calcs": sorted(set(re.findall(r"dash\.calc\(\s*['\"]([A-Za-z0-9_-]+)['\"]", every))),
    }


# ---------------------------------------------------------------- writing


class Writer:
    """Writes only under the dashboard folder."""

    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.written: list[str] = []

    def write(self, rel: str, text: str) -> None:
        path = (self.folder / rel).resolve()
        if self.folder not in path.parents:
            raise BundleError(f"refusing to write outside {self.folder}: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        self.written.append(rel)


def q(value) -> str:
    """A YAML scalar: JSON strings and numbers are valid YAML."""
    return json.dumps(value, ensure_ascii=False)


def comment_safe(text: str) -> str:
    text = re.sub(r"https?://\S+", "<link removed>", one_line(text))
    return text.replace("\n", " ")


def stub_sql(r: DatasetResult, source_note: str, file: bool, foreign_sql: str | None = None) -> str:
    lines = [f"{STUB_MARK} ({r.id}: {comment_safe(r.title)})."]
    if file:
        lines += ["-- Until it is written the dataset is marked todo: true, and a local preview with PORTAL_PREVIEW_SNAPSHOTS=1",
                  f"-- shows snapshots/{r.id}.json instead."]
    else:
        lines += ["-- The artifact read it through a connector LakeBoard can't use, so it needs a Unity Catalog source",
                  "-- first (Lakehouse Federation or ingestion into a Databricks table). Until then it is marked todo: true."]
    lines += ["-- Read-only: one SELECT/WITH, tables as catalog.schema.table (prod catalog name), filter values as",
              "-- :name parameters declared in dashboard.yml.",
              f"-- In the artifact: {comment_safe(source_note)}"]
    if r.description:
        lines.append(f"-- Artifact description: {comment_safe(r.description)}")
    if file and r.updated:
        lines.append(f"-- Snapshot saved in the artifact: {comment_safe(r.updated)}")
    lines.append("-- Tables named in the description: " + (", ".join(r.tables) or "none; ask the author"))
    if r.columns:
        lines.append("-- Columns the page reads (from the snapshot, same names and order): " + ", ".join(r.columns))
    elif file:
        lines.append("-- Columns the page reads: unknown until the data file is downloaded (see IMPORT.md)")
    else:
        lines.append("-- Columns the page reads: see the artifact's query below and the page")
    if foreign_sql:
        lines.append("-- The artifact's query, in the connector's own SQL dialect:")
        lines += [f"-- | {ln}" for ln in foreign_sql.strip().splitlines()]
    lines.append("-- TODO")
    return "\n".join(lines) + "\n"


def import_bundle(bundle: Path, slug: str, blobs: Path | None = None, force: bool = False,
                  root: Path = DASHBOARDS, today: dt.date | None = None) -> tuple[Path, list[str]]:
    """Does the import. Returns (dashboard folder, report lines). Raises BundleError on unreadable input."""
    if not SLUG_RE.match(slug):
        raise BundleError(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    if not bundle.is_dir():
        raise BundleError(f"{bundle} is not a folder")
    if not any((bundle / c).is_dir() for c in ("dash", "datasets", "files")):
        raise BundleError(f"{bundle} has none of dash/, datasets/, files/ (ArtifactData list output)")
    dash = read_collection(bundle, "dash")
    raw_sets = read_collection(bundle, "datasets")
    files = read_collection(bundle, "files")
    folder = root / slug
    if folder.exists() and not force:
        raise FileExistsError(f"{folder} already exists; pass --force to overwrite the files the import writes")
    today = today or dt.date.today()
    warnings: list[str] = []
    meta = dash.get("meta", {})
    title = one_line(meta.get("title")) or slug.replace("-", " ").capitalize()
    defaults = dash.get("params", {})
    if not isinstance(defaults, dict):
        raise BundleError("dash/params.json must be an object of name: default")
    recovered = routine_sql(dash, set(raw_sets), warnings)

    # files -> index.html + assets/
    page, assets = "", {}
    for name, doc in files.items():
        text = doc.get("text")
        if not isinstance(text, str):
            raise BundleError(f"files/{name}.json has no text")
        if name == "index.html":
            page = text
        elif not ASSET_NAME_RE.match(name) or ".." in name:
            warnings.append(f"file {name!r} skipped: not a plain file name (letters, digits, '-', '_', '.')")
        elif Path(name).suffix.lower() not in ASSET_TYPES:
            warnings.append(f"file {name!r} skipped: the portal serves only {', '.join(sorted(ASSET_TYPES))} from assets/; "
                            "ask the author what it is for")
        else:
            assets[name] = text
    if not page:
        warnings.append("the artifact has no index.html; the dashboard has no page")

    # datasets
    results: list[DatasetResult] = []
    rules: dict[str, dict] = {}
    used: set[str] = set()
    snapshots: dict[str, dict] = {}
    for ds_id, doc in raw_sets.items():
        src = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        upd = doc.get("updated") if isinstance(doc.get("updated"), dict) else {}
        r = DatasetResult(id=ds_id, title=one_line(doc.get("title")) or ds_id, description=one_line(doc.get("description")),
                          kind="needs-sql", updated=" by ".join(str(x) for x in (upd.get("at"), upd.get("by")) if x))
        r.tables = tables_named(r.description)
        if not DATASET_RE.match(ds_id) or not SNAPSHOT_ID_RE.match(ds_id):
            warnings.append(f"dataset id {ds_id!r} is not allowed in LakeBoard (letter or digit first, then letters, "
                            "digits, _ and -); skipped")
            continue
        for k in ("schedule", "staleAfterHours"):
            if doc.get(k) not in (None, ""):
                r.notes.append(f"artifact {k}: {comment_safe(json.dumps(doc[k], ensure_ascii=False))}")
        kind = str(src.get("kind") or "query").lower()
        if kind == "file":
            name = str(src.get("name") or "")
            r.detail = f"attached file {name or '(no name)'} ({src.get('format') or 'format from name'})"
            blob = find_blob(blobs, str(src.get("url") or ""), name)
            if blob is None:
                asset = re.search(r"[0-9a-f]{32}", str(src.get("url") or ""))
                r.notes.append("data file not downloaded: Artifact read with path "
                               f"{asset.group(0) if asset else '(asset id missing)'}, then import again with --blobs --force")
            else:
                try:
                    cols, rows = snapshot_from(blob, str(src.get("format") or ""), name)
                    snapshots[ds_id] = {"columns": cols, "rows": rows}
                    r.columns, r.rows, r.snapshot = cols, len(rows), True
                    if blob.stat().st_size > 20_000_000:
                        r.notes.append("the data file is over 20 MB, more than the local snapshot preview loads")
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                    r.notes.append(f"data file {blob.name} could not be turned into a snapshot: {e}")
            r.sql = stub_sql(r, r.detail, file=True)
            if ds_id in recovered:  # the scheduled task's SQL: a candidate, still todo until it reconciles
                doc_name, routine = recovered[ds_id]
                converted, names, lit_notes, _ = to_lakeboard_sql(routine)
                used |= set(names)
                r.notes += lit_notes
                r.notes.append(f"SQL recovered from dash/{doc_name} (the artifact's refresh routine); the instruction "
                               "text around it was not used")
                r.tables += [t for t in registry.tables_in(converted) if t not in r.tables]
                problems = sql_problems(converted)
                r.kind = "recovered-failed" if problems else "recovered"
                r.notes += [f"fails LakeBoard's SQL rules: {p}" for p in problems]
                head = [f"-- {r.title}. Recovered from the artifact's dash/{doc_name} refresh routine ({today}).",
                        f"-- Reconcile with the snapshot (scripts/compare_snapshot.py --dataset {ds_id}) before removing "
                        "todo: true and snapshot: from dashboard.yml."]
                if r.description:
                    head.append(f"-- Artifact description: {comment_safe(r.description)}")
                if r.columns:
                    head.append("-- Columns the page reads (from the snapshot): " + ", ".join(r.columns))
                r.sql = "\n".join(head) + "\n" + converted + "\n"
        else:
            connector = str(src.get("connector") or "")
            tool = str(src.get("tool") or "")
            arg, sql = find_sql_arg(src, doc.get("langs") if isinstance(doc.get("langs"), dict) else {})
            is_databricks = sql is not None and ("databricks" in connector.lower() or (not connector and kind == "query"))
            r.detail = f"live query: connector {connector or '(none named)'}, tool {tool or '(none)'}"
            if not is_databricks:
                r.kind = "unsupported-connector"
                r.notes.append("needs a Unity Catalog source: Lakehouse Federation or ingestion into a Databricks table")
                if sql:
                    r.notes.append("the artifact's query is kept in the stub as a starting point")
                r.sql = stub_sql(r, r.detail, file=False, foreign_sql=sql)
            else:
                if not connector:
                    r.notes.append("no connector named (older form); assumed Databricks SQL, confirm with the author")
                converted, names, lit_notes, bare = to_lakeboard_sql(sql)
                used |= set(names)
                r.notes += lit_notes
                if bare and kind == "call":
                    r.notes.append(f"unquoted blanks {bare} became parameters; check none was a column name or SQL text")
                ds_rules = src.get("rules") if isinstance(src.get("rules"), dict) else {}
                for k, v in ds_rules.items():
                    if k in rules and rules[k] != v:
                        warnings.append(f"parameter {k}: datasets give different rules; {ds_id}'s are used")
                    rules[k] = v
                other_args = {k: v for k, v in (src.get("args") or {}).items() if k != arg} if isinstance(src.get("args"), dict) else {}
                head = [f"-- {r.title}. Converted from the Claude artifact's {connector or 'SQL'} query ({today})."]
                if r.description:
                    head.append(f"-- Artifact description: {comment_safe(r.description)}")
                if other_args:
                    head.append(f"-- Other connector arguments (not used here): {comment_safe(json.dumps(other_args, ensure_ascii=False))}")
                if ds_rules:
                    head.append(f"-- Artifact rules: {comment_safe(json.dumps(ds_rules, ensure_ascii=False))}")
                problems = sql_problems(converted)
                r.kind = "check-failed" if problems else "converted"
                r.notes += [f"fails LakeBoard's SQL rules: {p}" for p in problems]
                r.sql = "\n".join(head) + "\n" + converted + "\n"
                r.detail += f", SQL in argument {arg!r}"
        results.append(r)

    params = build_params(defaults, rules, used, warnings)
    for name, spec in params.items():
        if spec["unenforced"]:
            note = f"-- LakeBoard checks only the type of :{name} ({spec['type']}); not enforced: {', '.join(spec['unenforced'])}\n"
            for r in results:
                if r.kind in SQL_KINDS and re.search(rf"(?<![:\w]):{name}\b", r.sql):
                    first, _, rest = r.sql.partition("\n")
                    r.sql = first + "\n" + note + rest
    for r in results:  # every :name in converted SQL must be declared (registry rule)
        if r.kind in ("converted", "recovered"):
            missing = [p for p in PARAM_RE.findall(strip_sql_comments_and_strings(r.sql)) if p not in params]
            if missing:
                r.kind = "check-failed" if r.kind == "converted" else "recovered-failed"
                r.notes.append(f"fails LakeBoard's SQL rules: parameters {sorted(set(missing))} are not declared")
    for r in results:  # SQL that breaks the rules is kept as comments, so the draft still loads (todo: true)
        if r.kind in ("check-failed", "recovered-failed"):
            reasons = "; ".join(n.split(": ", 1)[1] for n in r.notes if n.startswith("fails LakeBoard's SQL rules"))
            r.sql = (f"-- TODO: IMPORT CHECK FAILED, so the {'recovered' if r.kind == 'recovered-failed' else 'converted'} "
                     "query is kept below as comments. Fix it, uncomment\n"
                     f"-- it, reconcile it and remove todo: true. Problems: {comment_safe(reasons)}\n"
                     + "".join(f"-- | {ln}\n" for ln in r.sql.splitlines()))
    for ds_id, (doc_name, _) in recovered.items():
        if not any(r.id == ds_id and r.kind.startswith("recovered") for r in results):
            warnings.append(f"dash/{doc_name}: SQL for {ds_id!r} not used (only file datasets take a refresh routine's SQL)")

    scan = scan_page(page, assets)
    for ds in scan["datasets_read"]:
        if ds not in {r.id for r in results} and ds not in scan["calcs"]:
            warnings.append(f"the page reads dataset {ds!r}, which the artifact does not define")

    # write
    folder.mkdir(parents=True, exist_ok=True)
    w = Writer(folder)
    w.write("dashboard.yml", manifest(title, today, results, params))
    if page:
        w.write("index.html", page)
    for name, text in sorted(assets.items()):
        w.write(f"assets/{name}", text)
    for r in results:
        w.write(f"sql/{r.id}.sql", r.sql)
    for ds_id, snap in snapshots.items():
        w.write(f"snapshots/{ds_id}.json", json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
    if snapshots:
        info = {r.id: {"saved": r.updated, "rows": r.rows, "imported": str(today)} for r in results if r.snapshot}
        w.write("snapshots/_import.json", json.dumps(info, indent=2, ensure_ascii=False) + "\n")
    try:  # the portal's own check of what was written
        board = registry.load_dashboard(folder, env="prod")
        warnings += [f"portal check: {e}" for e in board.errors]
    except Exception as e:  # noqa: BLE001 - reported, not fatal
        warnings.append(f"portal check could not load the dashboard: {e}")
    w.write("IMPORT.md", import_md(title, slug, today, results, params, scan, warnings))
    return folder, summary(slug, results, scan, warnings)


def manifest(title: str, today: dt.date, results: list[DatasetResult], params: dict) -> str:
    names = ", ".join(r.title for r in results[:6]) + (", ..." if len(results) > 6 else "")
    desc = f"Draft imported from a Claude dashboard. Data: {names}." if results else "Draft imported from a Claude dashboard."
    out = [
        f"# Imported from a Claude Dashboard artifact on {today} by scripts/import_artifact.py. See IMPORT.md.",
        "# A draft: it shows under Drafts to the drafts_groups in src/environments.yml plus the groups below.",
        f"title: {q(title)}",
        f"description: {q(desc)}",
        "owner: TODO                 # the team that will own it",
        "section: Drafts",
        "status: draft",
        "page: artifact              # the page is the artifact's HTML; its extra files are in assets/",
        "order: 100",
        "groups: []                  # extra workspace groups that may open the draft ([] = drafts_groups only)",
        f"imported_from: {q(comment_safe(f'Claude artifact {title!r}, imported {today}'))}",
    ]
    if params:
        out.append("params:")
        for name, spec in params.items():
            line = f"  {name}: {{type: {spec['type']}" + (f", default: {q(spec['default'])}" if "default" in spec else "") + "}"
            if spec["unenforced"]:
                line += f"   # artifact rule not enforced: {comment_safe(', '.join(spec['unenforced']))}"
            out.append(line)
    out.append("datasets:")
    for r in results:
        out += [f"  {r.id}:", f"    title: {q(r.title)}"]
        if r.description:
            out.append(f"    description: {q(r.description)}")
        out.append(f"    sql: sql/{r.id}.sql")
        if r.kind != "converted":
            out.append(f"    todo: true                # {r.kind}: see IMPORT.md")
            if r.snapshot:
                out.append(f"    snapshot: snapshots/{r.id}.json   # local preview only; gitignored, never commit")
    if not results:
        out.append("  {}")
    return "\n".join(out) + "\n"


SQL_KINDS = ("converted", "check-failed", "recovered", "recovered-failed")  # datasets whose SQL file holds a query
STATUS = {
    "converted": "converted to SQL",
    "needs-sql": "needs SQL (snapshot of the artifact's file)",
    "unsupported-connector": "unsupported connector (needs a Unity Catalog source)",
    "check-failed": "converted, but fails LakeBoard's SQL rules",
    "recovered": "SQL recovered from refresh routine (reconcile)",
    "recovered-failed": "SQL recovered from refresh routine, but fails LakeBoard's SQL rules",
}


def import_md(title: str, slug: str, today: dt.date, results: list[DatasetResult], params: dict, scan: dict,
              warnings: list[str]) -> str:
    md = [f"# Import of \"{title}\"", "",
          f"Imported on {today} from a Claude Dashboard artifact by `scripts/import_artifact.py`. The dashboard is a "
          "draft (`status: draft`, section Drafts). Procedure: `.claude/skills/import-claude-dashboard/SKILL.md`.",
          "Snapshots in `snapshots/` are the artifact's data as last saved there; they are gitignored and must never "
          "be committed.", "", "## Datasets", "",
          "| Dataset | Status | Columns | Snapshot rows |", "|---|---|---|---|"]
    for r in results:
        md.append(f"| `{r.id}` {r.title} | {STATUS[r.kind]} | {len(r.columns) or '–'} | "
                  f"{r.rows if r.rows is not None else '–'} |")
    for r in results:
        md += ["", f"### `{r.id}`: {r.title}", "", f"- Status: {STATUS[r.kind]}", f"- In the artifact: {r.detail}"]
        if r.description:
            md.append(f"- Description: {r.description}")
        if r.updated:
            md.append(f"- Last saved in the artifact: {r.updated}")
        if r.tables:
            md.append("- Tables named: " + ", ".join(f"`{t}`" for t in r.tables))
        if r.columns:
            md.append("- Columns: " + ", ".join(f"`{c}`" for c in r.columns))
        md += [f"- Note: {n}" for n in r.notes]
    md += ["", "## Parameters", ""]
    if params:
        md += ["| Name | Type | Default | Artifact rules LakeBoard does not enforce |", "|---|---|---|---|"]
        for name, spec in params.items():
            md.append(f"| `{name}` | {spec['type']} | {q(spec['default']) if 'default' in spec else 'none (NULL)'} | "
                      f"{', '.join(spec['unenforced']) or '–'} |")
        md.append("")
        md.append("LakeBoard binds each value as a typed parameter, so values can't change the SQL, but it does not "
                  "check lists of allowed values or patterns. A parameter with no default is NULL until set.")
    else:
        md.append("None.")
    md += ["", "## Page scan", "",
           "- `dash` calls: " + (", ".join(f"`{k}` x{v}" for k, v in scan["dash"].items()) or "none"),
           "- `dash` calls the portal does not provide (src/static/dash.js): "
           + (", ".join(f"`{f}`" for f in scan["not_in_portal"]) or "none"),
           "- Calculated datasets (`dash.calc`): " + (", ".join(f"`{c}`" for c in scan["calcs"]) or "none"),
           f"- `data-draw` elements: {scan['data_draw']}",
           "- Dash meta tags: " + (", ".join(f"`{m}`" for m in scan["meta"]) or "none"),
           "- Extra files (in `assets/`): " + (", ".join(f"`{a}`" for a in scan["assets"]) or "none")]
    if scan["loader"]:
        md.append(f"- `dash.loader` used {scan['loader']} time(s): in the artifact it turned a connector's raw answer "
                  "into rows; in the portal it gets the SQL's rows, so check it still works once the SQL is written")
    if scan["missing_assets"]:
        md.append("- Referenced but not in the artifact: " + ", ".join(f"`{a}`" for a in scan["missing_assets"]))
    if scan["unreferenced_assets"]:
        md.append("- Extra files the page does not reference directly: " + ", ".join(f"`{a}`" for a in scan["unreferenced_assets"]))
    md.append("- Unsupported in the portal (external URLs, fetch, iframes, forms): "
              + ("none" if not scan["unsupported"] else ""))
    md += [f"  - {u}" for u in scan["unsupported"]]
    md.append("- Theme tokens the page defines itself: " + (", ".join(f"`{t}`" for t in scan["custom_tokens"]) or "none"))
    md.append("- Theme tokens used but not guaranteed by the portal: "
              + (", ".join(f"`{t}`" for t in scan["unknown_tokens"]) or "none"))
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {x}" for x in warnings]
    todo = [r for r in results if r.kind != "converted"]
    md += ["", "## Next steps", "",
           "- [ ] Set `owner:` in `dashboard.yml`, and `groups:` if people outside the drafts groups should see it"]
    if any(not r.snapshot and r.kind == "needs-sql" for r in results):
        md.append("- [ ] Download the missing data files and import again with `--blobs <dir> --force`")
    for r in todo:
        if r.kind == "needs-sql":
            md.append(f"- [ ] Write `sql/{r.id}.sql` from the tables named and Unity Catalog (never guess column names), "
                      f"then `python scripts/compare_snapshot.py --slug {slug} --dataset {r.id} --profile <p> --warehouse <id>`; "
                      "remove `todo:`/`snapshot:` when it reconciles")
        elif r.kind == "recovered":
            md.append(f"- [ ] Reconcile the recovered `sql/{r.id}.sql`: `python scripts/compare_snapshot.py --slug {slug} "
                      f"--dataset {r.id} --profile <p> --warehouse <id>`; remove `todo:`/`snapshot:` only when it reconciles")
        elif r.kind == "recovered-failed":
            md.append(f"- [ ] `{r.id}`: fix the recovered SQL's rule failures listed above (e.g. map its catalog to an "
                      "allowed one), uncomment it, reconcile with `compare_snapshot.py`, then remove `todo:`/`snapshot:`")
        elif r.kind == "unsupported-connector":
            md.append(f"- [ ] `{r.id}`: agree a Unity Catalog source (Lakehouse Federation or ingestion), write the SQL, remove `todo:`")
        else:
            md.append(f"- [ ] `{r.id}`: fix the SQL rule failures listed above, remove `todo:`")
    md += ["- [ ] `python scripts/check.py --static` and `python -m pytest -q`",
           f"- [ ] Preview locally with snapshots (`PORTAL_PREVIEW_SNAPSHOTS=1`), then live; open `/d/{slug}` with no console errors",
           "- [ ] Ask the author before changing what the page shows; keep the HTML unchanged unless it can't run",
           "- [ ] Delete `snapshots/` when every dataset reconciles, then open the pull request"]
    return "\n".join(md) + "\n"


def summary(slug: str, results: list[DatasetResult], scan: dict, warnings: list[str]) -> list[str]:
    lines = [f"{r.id}: {STATUS[r.kind]}" + (f", snapshot {r.rows} rows" if r.snapshot else "") for r in results]
    lines.append(f"page: {scan['data_draw']} data-draw, dash calls {', '.join(scan['dash']) or 'none'}, "
                 f"{len(scan['assets'])} extra files, {len(scan['unsupported'])} unsupported uses, "
                 f"{len(scan['unknown_tokens'])} unknown tokens")
    return lines + [f"warning: {x}" for x in warnings]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bundle", required=True, type=Path, help="folder ArtifactData list wrote (dash/, datasets/, files/)")
    ap.add_argument("--slug", required=True, help="folder name under src/dashboards (lowercase, digits, hyphens)")
    ap.add_argument("--blobs", type=Path, help="folder with the downloaded data files (named by asset id or file name)")
    ap.add_argument("--force", action="store_true", help="overwrite the files the import writes in an existing folder")
    ap.add_argument("--root", type=Path, default=DASHBOARDS, help=argparse.SUPPRESS)  # tests
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # artifact titles may hold characters a Windows console can't show
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        folder, lines = import_bundle(a.bundle, a.slug, a.blobs, a.force, a.root)
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"created {folder}")
    for ln in lines:
        print(f"  {ln}")
    print(f"next: read {folder / 'IMPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
