"""Summarises a Power BI Project (PBIP) so you can plan its LakeBoard dashboard: tables, sources, measures,
relationships, row-level security and report pages.

    python scripts/pbip_summary.py path/to/Sales.pbip
    python scripts/pbip_summary.py path/to/Sales.Report          # or Sales.SemanticModel, or a folder holding them
    python scripts/pbip_summary.py path/to/project --json        # the same, as JSON

Reads files only. It never runs M, DAX or anything else, and never connects to Power BI or Databricks.

Formats it reads (Microsoft Learn, "Power BI Desktop projects" and the json-schemas repository):
  * Semantic model: TMDL (<name>.SemanticModel/definition/: model.tmdl, tables/*.tmdl, relationships.tmdl,
    expressions.tmdl, roles/*.tmdl) or TMSL (<name>.SemanticModel/model.bim).
  * Report: PBIR (<name>.Report/definition/pages/<page>/page.json and visuals/<visual>/visual.json) or
    PBIR-Legacy (<name>.Report/report.json, where each visual's `config` is JSON inside a string).
Anything it can't read is listed under "warnings" rather than stopping the run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------------
# Finding the parts
# ---------------------------------------------------------------------------------------------------------------


def _read_json(path: Path, warnings: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        warnings.append(f"{path}: could not read JSON ({e})")
        return None


def locate(path: Path, warnings: list[str]) -> tuple[Path | None, Path | None]:
    """Returns (report folder, semantic model folder) for a .pbip file, a .pbir file, a .Report or
    .SemanticModel/.Dataset folder, or a folder that holds them."""
    path = path.resolve()
    report = model = None
    fallback_models: list[Path] = []
    if path.is_file() and path.suffix.lower() == ".pbip":
        data = _read_json(path, warnings) or {}
        for art in data.get("artifacts") or []:
            rel = ((art or {}).get("report") or {}).get("path")
            if rel:
                report = (path.parent / rel).resolve()
                break
        if report is None:
            stem = path.stem
            cand = path.parent / f"{stem}.Report"
            report = cand if cand.is_dir() else None
    elif path.is_file() and path.suffix.lower() == ".pbir":
        report = path.parent
    elif path.is_file() and path.name.lower() == "model.bim":
        model = path.parent
    elif path.is_dir():
        name = path.name.lower()
        if name.endswith(".report"):
            report = path
        elif name.endswith(".semanticmodel") or name.endswith(".dataset"):
            model = path
        else:
            reports = sorted(p for p in path.iterdir() if p.is_dir() and p.name.lower().endswith(".report"))
            models = sorted(p for p in path.iterdir() if p.is_dir()
                            and (p.name.lower().endswith(".semanticmodel") or p.name.lower().endswith(".dataset")))
            if len(reports) > 1:
                warnings.append(f"{len(reports)} reports in {path}; summarising {reports[0].name}. "
                                "Pass a .pbip or .Report folder to choose another.")
            report = reports[0] if reports else None
            if models and report is None:
                model = models[0]
            fallback_models = models  # used when the report's definition.pbir doesn't say
    else:
        raise SystemExit(f"{path}: not a .pbip file or a Power BI Project folder")

    if report is not None and model is None:
        pbir = _read_json(report / "definition.pbir", warnings) or {}
        ref = pbir.get("datasetReference") or {}
        rel = (ref.get("byPath") or {}).get("path")
        if rel:
            model = (report / rel).resolve()
        elif ref.get("byConnection"):
            warnings.append("The report connects live to a published semantic model (byConnection); "
                            "the model is not in this folder. Summarise the model's own project too.")
        if model is None:
            stem = report.name[: -len(".report")]
            for suffix in (".SemanticModel", ".Dataset"):
                cand = report.parent / f"{stem}{suffix}"
                if cand.is_dir():
                    model = cand
                    break
        if model is None and fallback_models:
            model = fallback_models[0]
    if report is not None and not report.is_dir():
        warnings.append(f"report folder not found: {report}")
        report = None
    if model is not None and not model.is_dir():
        warnings.append(f"semantic model folder not found: {model}")
        model = None
    return report, model


# ---------------------------------------------------------------------------------------------------------------
# TMDL
# ---------------------------------------------------------------------------------------------------------------

TMDL_OBJECTS = {
    "database", "model", "table", "column", "measure", "partition", "hierarchy", "level", "relationship", "role",
    "tablepermission", "columnpermission", "member", "expression", "annotation", "culture", "perspective",
    "perspectivetable", "perspectivecolumn", "perspectivemeasure", "perspectivehierarchy", "calculationgroup",
    "calculationitem", "datasource", "function", "querygroup", "extendedproperty", "changedproperty",
    "formatstringdefinition", "detailrowsdefinition", "kpi", "linguisticmetadata", "variation", "datacoverage",
    "datacoveragedefinition", "alternateof", "refreshpolicy", "calendar", "calculationexpression",
}


def _indent(line: str) -> int:
    n = 0
    spaces = 0
    for ch in line:
        if ch == "\t":
            n += 1
            spaces = 0
        elif ch == " ":
            spaces += 1
            if spaces == 4:
                n += 1
                spaces = 0
        else:
            break
    return n


def _strip_indent(line: str, levels: int) -> str:
    out = line
    for _ in range(levels):
        if out.startswith("\t"):
            out = out[1:]
        elif out.startswith("    "):
            out = out[4:]
        else:
            break
    return out


def _parse_name(text: str) -> tuple[str, str]:
    """Reads a TMDL object name (bare or 'quoted', '' escapes a quote). Returns (name, rest)."""
    text = text.lstrip()
    if text.startswith("'"):
        i, out = 1, []
        while i < len(text):
            if text[i] == "'":
                if text[i + 1: i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), text[i + 1:]
            out.append(text[i])
            i += 1
        return "".join(out), ""
    m = re.match(r"([^\s=:]+)(.*)", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('""', '"')
    return v


class _Node(dict):
    pass


def _collect_expression(lines: list[str], i: int, first: str, min_indent: int) -> tuple[str, int]:
    """Gathers an expression that starts after '=' (``first``) and continues on lines indented at least
    ``min_indent`` levels. Handles ``` fenced expressions. Returns (text, next line index)."""
    first = first.strip()
    if first.startswith("```"):
        body, j = [], i
        rest = first[3:]
        if rest.strip():
            body.append(rest)
        while j < len(lines) and lines[j].strip() != "```" and not lines[j].rstrip().endswith("```"):
            body.append(lines[j])
            j += 1
        if j < len(lines):
            tail = lines[j].rstrip()[:-3]
            if tail.strip():
                body.append(tail)
            j += 1
        return _dedent(body), j
    body = [first] if first else []
    j = i
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "":
            body.append("")
            j += 1
            continue
        if _indent(ln) >= min_indent:
            body.append(_strip_indent(ln, min_indent))
            j += 1
            continue
        break
    while body and body[-1].strip() == "":
        body.pop()
    # back off trailing blank lines so the caller sees them as separators
    while j > i and lines[j - 1].strip() == "":
        j -= 1
    return "\n".join(body).strip("\n"), j


def _dedent(body: list[str]) -> str:
    rows = [b.rstrip() for b in body]
    pads = [len(r) - len(r.lstrip()) for r in rows if r.strip()]
    cut = min(pads) if pads else 0
    return "\n".join(r[cut:] for r in rows).strip("\n")


def parse_tmdl(text: str) -> list[_Node]:
    """Parses TMDL into nested nodes: {type, name, value, props, children, description}."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    nodes, _ = _parse_block(lines, 0, 0)
    return nodes


def _parse_block(lines: list[str], i: int, level: int) -> tuple[list[_Node], int]:
    nodes: list[_Node] = []
    desc: list[str] = []
    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "":
            i += 1
            continue
        ind = _indent(raw)
        if ind < level:
            break
        if ind > level:  # stray deeper line: skip it
            i += 1
            continue
        s = raw.strip()
        if s.startswith("///"):
            desc.append(s[3:].strip())
            i += 1
            continue
        word = re.match(r"([A-Za-z]+)", s)
        kw = word.group(1) if word else ""
        if kw.lower() == "ref":
            i += 1
            desc = []
            continue
        if kw.lower() in TMDL_OBJECTS and len(s) > len(kw) and s[len(kw)] in " \t":
            name, rest = _parse_name(s[len(kw):])
            node = _Node(type=kw.lower(), name=name, value=None, props={}, children=[],
                         description=" ".join(desc) or None)
            desc = []
            rest = rest.strip()
            i += 1
            if rest.startswith("="):
                node["value"], i = _collect_expression(lines, i, rest[1:], level + 2)
            elif rest.startswith(":"):  # e.g. "annotation X: value" style is not TMDL, but be lenient
                node["value"] = _unquote(rest[1:])
            children, i = _parse_block(lines, i, level + 1)
            for c in children:
                if c.get("type") == "_prop":
                    node["props"][c["name"]] = c["value"]
                else:
                    node["children"].append(c)
            nodes.append(node)
            continue
        # a property: "key: value", "key = expression" or a bare boolean "isHidden"
        m = re.match(r"([A-Za-z_][\w]*)\s*([:=])\s*(.*)$", s, re.S)
        i += 1
        if m:
            key, sep, rest = m.group(1), m.group(2), m.group(3)
            if sep == "=":
                value, i = _collect_expression(lines, i, rest, level + 1)
            else:
                value = _unquote(rest)
            nodes.append(_Node(type="_prop", name=key, value=value))
        else:
            nodes.append(_Node(type="_prop", name=s, value=True))
        desc = []
    return nodes, i


def _prop(node: dict, key: str, default=None):
    for k, v in (node.get("props") or {}).items():
        if k.lower() == key.lower():
            return v
    return default


def _flag(node: dict, key: str) -> bool:
    v = _prop(node, key, False)
    return v is True or str(v).strip().lower() == "true"


def load_tmdl(folder: Path, warnings: list[str]) -> dict:
    """Builds the neutral model dict from a TMDL definition folder."""
    nodes: list[_Node] = []
    files = sorted(folder.rglob("*.tmdl"))
    for f in files:
        try:
            nodes.extend(parse_tmdl(f.read_text(encoding="utf-8-sig")))
        except Exception as e:  # noqa: BLE001 - one bad file shouldn't stop the summary
            warnings.append(f"{f}: could not parse TMDL ({e})")
    tables: dict[str, dict] = {}
    rels, roles, exprs = [], [], []

    def flatten(ns):
        for n in ns:
            yield n
            if n["type"] in ("model", "database"):
                yield from flatten(n["children"])

    for n in flatten(nodes):
        t = n["type"]
        if t == "table":
            tab = tables.setdefault(n["name"], _new_table(n["name"]))
            tab["hidden"] = tab["hidden"] or _flag(n, "isHidden")
            tab["description"] = tab["description"] or n.get("description")
            for c in n["children"]:
                ct = c["type"]
                if ct == "column":
                    tab["columns"].append({
                        "name": c["name"], "data_type": _prop(c, "dataType"), "hidden": _flag(c, "isHidden"),
                        "source_column": _prop(c, "sourceColumn"), "expression": c.get("value"),
                        "calculated": c.get("value") is not None, "format": _prop(c, "formatString"),
                        "description": c.get("description"),
                    })
                elif ct == "measure":
                    tab["measures"].append({
                        "name": c["name"], "expression": c.get("value") or "", "format": _prop(c, "formatString"),
                        "hidden": _flag(c, "isHidden"), "folder": _prop(c, "displayFolder"),
                        "description": c.get("description"),
                    })
                elif ct == "partition":
                    kind = (c.get("value") or "").strip().lower()
                    tab["partitions"].append({
                        "name": c["name"], "type": kind or None, "mode": _prop(c, "mode"),
                        "expression": _prop(c, "source") if isinstance(_prop(c, "source"), str) else None,
                        "entity": _prop(c, "entityName"), "schema": _prop(c, "schemaName"),
                        "expression_source": _prop(c, "expressionSource"),
                    })
                elif ct == "calculationgroup":
                    tab["calculation_group"] = [
                        {"name": ci["name"], "expression": ci.get("value") or ""}
                        for ci in c["children"] if ci["type"] == "calculationitem"]
        elif t == "relationship":
            rels.append(_rel_from(n["name"], _prop(n, "fromColumn"), _prop(n, "toColumn"),
                                  _prop(n, "fromCardinality"), _prop(n, "toCardinality"),
                                  _prop(n, "crossFilteringBehavior"), _prop(n, "isActive"),
                                  _prop(n, "securityFilteringBehavior")))
        elif t == "role":
            roles.append({
                "name": n["name"], "permission": _prop(n, "modelPermission"),
                "filters": [{"table": tp["name"], "expression": tp.get("value") or ""}
                            for tp in n["children"] if tp["type"] == "tablepermission"],
                "members": len([m for m in n["children"] if m["type"] == "member"]),
            })
        elif t == "expression":
            exprs.append({"name": n["name"], "expression": n.get("value") or "", "kind": _prop(n, "kind")})
    return {"format": "TMDL", "tables": list(tables.values()), "relationships": rels, "roles": roles,
            "expressions": exprs}


def _split_ref(ref: str | None) -> tuple[str | None, str | None]:
    """'Sales'.'Order Date' or Sales.OrderDate -> (Sales, Order Date)."""
    if not ref:
        return None, None
    ref = ref.strip()
    if ref.startswith("'"):
        table, rest = _parse_name(ref)
    else:
        table, _, rest = ref.partition(".")
        rest = "." + rest if rest else ""
    rest = rest.strip()
    if rest.startswith("."):
        col, _ = _parse_name(rest[1:])
        return table, col
    return table, None


def _rel_from(name, from_col, to_col, from_card, to_card, cross, active, security) -> dict:
    ft, fc = _split_ref(from_col) if isinstance(from_col, str) and "." in from_col else (None, from_col)
    tt, tc = _split_ref(to_col) if isinstance(to_col, str) and "." in to_col else (None, to_col)
    return {
        "name": name, "from_table": ft, "from_column": fc, "to_table": tt, "to_column": tc,
        "from_cardinality": (str(from_card) if from_card else "many"),
        "to_cardinality": (str(to_card) if to_card else "one"),
        "cross_filter": _cross(cross), "active": not (str(active).lower() == "false" or active is False),
        "security_filter": security,
    }


def _cross(v) -> str:
    s = str(v or "").lower()
    if s in ("bothdirections", "2", "both"):
        return "both"
    if s in ("automatic", "3"):
        return "automatic"
    return "single"


def _new_table(name: str) -> dict:
    return {"name": name, "hidden": False, "description": None, "columns": [], "measures": [], "partitions": [],
            "calculation_group": None}


# ---------------------------------------------------------------------------------------------------------------
# TMSL (model.bim)
# ---------------------------------------------------------------------------------------------------------------


def _text(v) -> str:
    """TMSL stores long expressions either as a string or as a list of lines."""
    if isinstance(v, list):
        return "\n".join(str(x) for x in v).strip()
    return "" if v is None else str(v).strip()


def load_bim(path: Path, warnings: list[str]) -> dict:
    data = _read_json(path, warnings) or {}
    model = data.get("model") or data  # a Database object wraps the model
    tables = []
    for t in model.get("tables") or []:
        tab = _new_table(t.get("name", ""))
        tab["hidden"] = bool(t.get("isHidden"))
        tab["description"] = _text(t.get("description")) or None
        for c in t.get("columns") or []:
            ctype = (c.get("type") or "data").lower()
            if ctype == "rownumber":
                continue
            tab["columns"].append({
                "name": c.get("name"), "data_type": c.get("dataType"), "hidden": bool(c.get("isHidden")),
                "source_column": c.get("sourceColumn"),
                "expression": _text(c.get("expression")) if ctype == "calculated" else None,
                "calculated": ctype == "calculated", "format": c.get("formatString"),
                "description": _text(c.get("description")) or None,
            })
        for m in t.get("measures") or []:
            tab["measures"].append({
                "name": m.get("name"), "expression": _text(m.get("expression")), "format": m.get("formatString"),
                "hidden": bool(m.get("isHidden")), "folder": m.get("displayFolder"),
                "description": _text(m.get("description")) or None,
            })
        for p in t.get("partitions") or []:
            src = p.get("source") or {}
            tab["partitions"].append({
                "name": p.get("name"), "type": (src.get("type") or "").lower() or None, "mode": p.get("mode"),
                "expression": _text(src.get("expression") or src.get("query")) or None,
                "entity": src.get("entityName"), "schema": src.get("schemaName"),
                "expression_source": src.get("expressionSource"),
            })
        cg = t.get("calculationGroup")
        if cg:
            tab["calculation_group"] = [{"name": ci.get("name"), "expression": _text(ci.get("expression"))}
                                        for ci in cg.get("calculationItems") or []]
        tables.append(tab)
    rels = []
    for r in model.get("relationships") or []:
        rel = _rel_from(r.get("name"), r.get("fromColumn"), r.get("toColumn"), r.get("fromCardinality"),
                        r.get("toCardinality"), r.get("crossFilteringBehavior"), r.get("isActive", True),
                        r.get("securityFilteringBehavior"))
        rel["from_table"], rel["to_table"] = r.get("fromTable"), r.get("toTable")
        rels.append(rel)
    roles = [{
        "name": r.get("name"), "permission": r.get("modelPermission"),
        "filters": [{"table": tp.get("name"), "expression": _text(tp.get("filterExpression"))}
                    for tp in r.get("tablePermissions") or [] if tp.get("filterExpression")],
        "members": len(r.get("members") or []),
    } for r in model.get("roles") or []]
    exprs = [{"name": e.get("name"), "expression": _text(e.get("expression")), "kind": e.get("kind")}
             for e in model.get("expressions") or []]
    return {"format": "TMSL (model.bim)", "tables": tables, "relationships": rels, "roles": roles,
            "expressions": exprs}


# ---------------------------------------------------------------------------------------------------------------
# Power Query (M) sources
# ---------------------------------------------------------------------------------------------------------------

M_CONNECTORS = [
    # (regex on the function name, kind shown)
    (r"(?:Databricks|DatabricksMultiCloud|AzureDatabricks)\.Catalogs", "Databricks"),
    (r"(?:Databricks|DatabricksMultiCloud|AzureDatabricks)\.Query", "Databricks (native SQL)"),
    (r"Sql\.Databases?", "SQL Server / Azure SQL"),
    (r"Snowflake\.Databases", "Snowflake"),
    (r"GoogleBigQuery\.Database", "BigQuery"),
    (r"AmazonRedshift\.Database", "Redshift"),
    (r"PostgreSQL\.Database", "PostgreSQL"),
    (r"Oracle\.Database", "Oracle"),
    (r"MySQL\.Database", "MySQL"),
    (r"Odbc\.(?:DataSource|Query)", "ODBC"),
    (r"OData\.Feed", "OData"),
    (r"Lakehouse\.Contents", "Fabric Lakehouse"),
    (r"Fabric\.Warehouse", "Fabric Warehouse"),
    (r"AnalysisServices\.Database", "Analysis Services"),
    (r"PowerPlatform\.Dataflows|PowerBI\.Dataflows", "Power BI dataflow"),
    (r"SharePoint\.(?:Files|Contents|Tables)", "SharePoint"),
    (r"Excel\.Workbook", "Excel"),
    (r"Csv\.Document", "CSV"),
    (r"Json\.Document", "JSON"),
    (r"Web\.Contents", "Web"),
    (r"File\.Contents", "File"),
    (r"Folder\.(?:Files|Contents)", "Folder"),
]

_STR = r'"((?:[^"]|"")*)"'


def _m_args(expr: str, func_pos: int) -> list[str]:
    """The raw top-level arguments of the call starting at the '(' after func_pos."""
    i = expr.find("(", func_pos)
    if i < 0:
        return []
    depth, cur, out, in_str = 0, [], [], False
    for ch in expr[i + 1:]:
        if in_str:
            cur.append(ch)
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _m_value(arg: str, params: dict[str, str]) -> str | None:
    arg = arg.strip()
    m = re.fullmatch(_STR, arg, re.S)
    if m:
        return m.group(1).replace('""', '"')
    name = arg[2:-1] if arg.startswith('#"') and arg.endswith('"') else arg
    if name in params:
        return params[name]
    return f"<{arg}>" if arg else None


def m_parameters(expressions: list[dict]) -> dict[str, str]:
    """Shared expressions marked IsParameterQuery=true, with their literal value."""
    out = {}
    for e in expressions:
        text = e.get("expression") or ""
        if "IsParameterQuery" in text:
            m = re.match(r"\s*" + _STR, text, re.S)
            if m:
                out[e["name"]] = m.group(1).replace('""', '"')
            else:
                m = re.match(r"\s*([^\s]+)\s+meta", text)
                if m:
                    out[e["name"]] = m.group(1)
    return out


def analyse_m(expr: str, params: dict[str, str] | None = None, queries: set[str] | None = None) -> dict:
    """Recognises the connector and the object an M query reads. Never evaluates anything."""
    params = params or {}
    out = {"kind": None, "server": None, "location": None, "database": None, "object": None, "native_sql": None,
           "references": []}
    if not expr:
        return out
    for pat, kind in M_CONNECTORS:
        m = re.search(r"\b(" + pat + r")\s*\(", expr)
        if not m:
            continue
        out["kind"] = kind
        args = _m_args(expr, m.start())
        fn = m.group(1)
        if kind.startswith("Databricks"):
            out["server"] = _m_value(args[0], params) if args else None
            if len(args) > 1:
                out["http_path"] = _m_value(args[1], params)
            if fn.endswith(".Query") and len(args) > 2:
                out["native_sql"] = _m_value(args[2], params)
            names = re.findall(r'\[\s*Name\s*=\s*' + _STR + r'\s*,\s*Kind\s*=\s*"(\w+)"\s*\]', expr)
            parts = {k.lower(): v.replace('""', '"') for v, k in names}
            opt = {k.lower(): v for k, v in re.findall(r'\b(Catalog|Database)\s*=\s*' + _STR, expr)}
            catalog = parts.get("database") or opt.get("catalog")
            schema = parts.get("schema") or opt.get("database")
            table = parts.get("table") or parts.get("view")
            if table:
                out["object"] = ".".join(x or "?" for x in (catalog, schema, table))
            out["database"] = catalog
        elif kind == "Snowflake":
            out["server"] = _m_value(args[0], params) if args else None
            names = re.findall(r'\[\s*Name\s*=\s*' + _STR + r'\s*,\s*Kind\s*=\s*"(\w+)"\s*\]', expr)
            parts = {k.lower(): v for v, k in names}
            table = parts.get("table") or parts.get("view")
            out["database"] = parts.get("database")
            if table:
                out["object"] = ".".join(x or "?" for x in (parts.get("database"), parts.get("schema"), table))
        elif kind.startswith("SQL Server") or kind in ("PostgreSQL", "Oracle", "MySQL", "Redshift"):
            out["server"] = _m_value(args[0], params) if args else None
            out["database"] = _m_value(args[1], params) if len(args) > 1 and not args[1].startswith("[") else None
            nav = re.search(r'\[\s*Schema\s*=\s*' + _STR + r'\s*,\s*Item\s*=\s*' + _STR + r'\s*\]', expr)
            if nav:
                out["object"] = f"{nav.group(1)}.{nav.group(2)}"
            q = re.search(r'\bQuery\s*=\s*' + _STR, expr, re.S)
            if q:
                out["native_sql"] = q.group(1).replace('""', '"')
        elif kind in ("SharePoint", "Web", "OData", "File", "Folder", "Fabric Lakehouse"):
            out["location"] = _m_value(args[0], params) if args else None
        elif kind == "Excel":
            inner = re.search(r'(SharePoint\.\w+|Web\.Contents|File\.Contents)\s*\(\s*' + _STR, expr)
            if inner:
                out["location"] = inner.group(2)
            sheet = re.search(r'\[\s*Item\s*=\s*' + _STR + r'\s*,\s*Kind\s*=\s*"(Sheet|Table|DefinedName)"', expr)
            if sheet:
                out["object"] = f"{sheet.group(2)} {sheet.group(1)}"
        break
    nq = re.search(r'Value\.NativeQuery\s*\(', expr)
    if nq:
        args = _m_args(expr, nq.start())
        if len(args) > 1:
            out["native_sql"] = _m_value(args[1], params)
    if out["kind"] is None and re.search(r"Table\.FromRows\s*\(\s*Json\.Document\s*\(\s*Binary\.Decompress", expr):
        out["kind"] = "Entered data (inside the model)"
    elif out["kind"] == "JSON" and "Binary.Decompress" in expr:
        out["kind"] = "Entered data (inside the model)"
    for q in sorted(queries or ()):
        if q in params:
            continue
        if re.search(r'(?<![\w"])' + re.escape(q) + r'(?![\w"])', expr) or f'#"{q}"' in expr:
            out["references"].append(q)
    return out


# ---------------------------------------------------------------------------------------------------------------
# DAX
# ---------------------------------------------------------------------------------------------------------------

DAX_CARE = {
    "time intelligence": [
        "SAMEPERIODLASTYEAR", "DATEADD", "DATESYTD", "DATESQTD", "DATESMTD", "TOTALYTD", "TOTALQTD", "TOTALMTD",
        "PARALLELPERIOD", "PREVIOUSDAY", "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSYEAR", "NEXTDAY",
        "NEXTMONTH", "NEXTQUARTER", "NEXTYEAR", "DATESBETWEEN", "DATESINPERIOD", "OPENINGBALANCEMONTH",
        "OPENINGBALANCEQUARTER", "OPENINGBALANCEYEAR", "CLOSINGBALANCEMONTH", "CLOSINGBALANCEQUARTER",
        "CLOSINGBALANCEYEAR", "STARTOFMONTH", "STARTOFQUARTER", "STARTOFYEAR", "ENDOFMONTH", "ENDOFQUARTER",
        "ENDOFYEAR", "FIRSTDATE", "LASTDATE", "FIRSTNONBLANK", "LASTNONBLANK",
    ],
    "filter context": [
        "CALCULATE", "CALCULATETABLE", "FILTER", "ALL", "ALLEXCEPT", "ALLSELECTED", "ALLNOBLANKROW",
        "REMOVEFILTERS", "KEEPFILTERS", "USERELATIONSHIP", "CROSSFILTER", "TREATAS", "SELECTEDVALUE",
        "HASONEVALUE", "HASONEFILTER", "ISFILTERED", "ISCROSSFILTERED", "ISINSCOPE", "VALUES", "FILTERS",
    ],
    "ranking / row context": ["RANKX", "RANK", "TOPN", "EARLIER", "EARLIEST", "WINDOW", "OFFSET", "INDEX"],
    "non-additive": ["DIVIDE", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "AVERAGE", "AVERAGEX", "MEDIAN",
                     "MEDIANX", "PERCENTILE.INC", "PERCENTILE.EXC", "PERCENTILEX.INC", "PERCENTILEX.EXC"],
    "security": ["USERPRINCIPALNAME", "USERNAME", "USEROBJECTID", "CUSTOMDATA"],
}


def _dax_code(expr: str) -> str:
    """DAX with comments and string literals blanked, so function names inside them don't count."""
    expr = re.sub(r"//[^\n]*|--[^\n]*", " ", expr)
    expr = re.sub(r"/\*.*?\*/", " ", expr, flags=re.S)
    expr = re.sub(r'"(?:[^"]|"")*"', '""', expr)
    return expr


def dax_flags(expr: str) -> dict[str, list[str]]:
    code = _dax_code(expr or "")
    no_refs = re.sub(r"'(?:[^']|'')*'|\[[^\]]*\]", " ", code)
    out = {}
    for cat, funcs in DAX_CARE.items():
        hit = [f for f in funcs if re.search(r"(?<![\w.])" + re.escape(f) + r"\s*\(", no_refs, re.I)]
        if cat == "non-additive" and re.search(r"(?<![/*])/(?![/*])", no_refs):
            hit.append("/")
        if hit:
            out[cat] = hit
    return out


def dax_refs(expr: str) -> dict[str, list[str]]:
    """Column references ('Table'[Col] / Table[Col]) and bare [Measure] references."""
    code = _dax_code(expr or "")
    cols, measures = [], []
    for m in re.finditer(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w]*))?\s*\[([^\]]+)\]", code):
        table = (m.group(1) or "").replace("''", "'") or m.group(2)
        if table and table.upper() in ("VAR", "RETURN"):
            table = None
        if table:
            ref = f"{table}[{m.group(3)}]"
            if ref not in cols:
                cols.append(ref)
        elif m.group(3) not in measures:
            measures.append(m.group(3))
    return {"columns": cols, "measures": measures}


# ---------------------------------------------------------------------------------------------------------------
# Report: fields and filters (shared by PBIR and PBIR-Legacy)
# ---------------------------------------------------------------------------------------------------------------

AGG = {0: "Sum", 1: "Average", 2: "DistinctCount", 3: "Min", 4: "Max", 5: "Count", 6: "Median",
       7: "StandardDeviation", 8: "Variance"}
COMPARE = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}


def _entity(expr: dict, aliases: dict[str, str]) -> str:
    src = (expr or {}).get("SourceRef") or {}
    if "Entity" in src:
        return src["Entity"]
    if "Source" in src:
        return aliases.get(src["Source"], src["Source"])
    if "PropertyVariationSource" in (expr or {}):
        pvs = expr["PropertyVariationSource"]
        return f"{_entity(pvs.get('Expression'), aliases)}.{pvs.get('Property')}"
    return "?"


def describe_field(f: dict, aliases: dict[str, str] | None = None) -> dict:
    """{kind, table, name, text} for a semantic query expression (Column, Measure, Aggregation, HierarchyLevel)."""
    aliases = aliases or {}
    f = f or {}
    if "Column" in f:
        c = f["Column"]
        t = _entity(c.get("Expression"), aliases)
        return {"kind": "column", "table": t, "name": c.get("Property"), "text": f"{t}.{c.get('Property')}"}
    if "Measure" in f:
        c = f["Measure"]
        t = _entity(c.get("Expression"), aliases)
        return {"kind": "measure", "table": t, "name": c.get("Property"), "text": f"{t}.[{c.get('Property')}]"}
    if "Aggregation" in f:
        a = f["Aggregation"]
        inner = describe_field(a.get("Expression"), aliases)
        fn = AGG.get(a.get("Function"), f"Agg{a.get('Function')}")
        return {"kind": "aggregation", "table": inner["table"], "name": inner["name"], "function": fn,
                "text": f"{fn}({inner['text']})"}
    if "HierarchyLevel" in f:
        h = f["HierarchyLevel"]
        hier = (h.get("Expression") or {}).get("Hierarchy") or {}
        t = _entity(hier.get("Expression"), aliases)
        return {"kind": "hierarchy level", "table": t, "name": h.get("Level"),
                "text": f"{t}.{hier.get('Hierarchy')}.{h.get('Level')}"}
    if "Literal" in f:
        v = f["Literal"].get("Value")
        return {"kind": "literal", "table": None, "name": v, "text": str(v)}
    return {"kind": "unknown", "table": None, "name": None, "text": json.dumps(f)[:80]}


def _literal(v: dict) -> str:
    lit = (v or {}).get("Literal") or {}
    val = str(lit.get("Value", "?"))
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1].replace("''", "'")
    if val.endswith("L") and val[:-1].lstrip("-").isdigit():
        return val[:-1]
    m = re.fullmatch(r"datetime'([^']*)'", val)
    return m.group(1) if m else val


def describe_condition(c: dict, aliases: dict[str, str]) -> str:
    c = c or {}
    if "In" in c:
        i = c["In"]
        fields = ", ".join(describe_field(e, aliases)["text"] for e in i.get("Expressions") or [])
        vals = ["/".join(_literal(x) for x in row) for row in i.get("Values") or []]
        return f"{fields} in ({', '.join(vals)})"
    if "Not" in c:
        return f"not ({describe_condition(c['Not'].get('Expression'), aliases)})"
    if "And" in c:
        return f"{describe_condition(c['And'].get('Left'), aliases)} and {describe_condition(c['And'].get('Right'), aliases)}"
    if "Or" in c:
        return f"({describe_condition(c['Or'].get('Left'), aliases)} or {describe_condition(c['Or'].get('Right'), aliases)})"
    if "Comparison" in c:
        k = c["Comparison"]
        left = describe_field(k.get("Left"), aliases)["text"]
        right = _literal(k.get("Right")) if "Literal" in (k.get("Right") or {}) else describe_field(k.get("Right"), aliases)["text"]
        return f"{left} {COMPARE.get(k.get('ComparisonKind'), '?')} {right}"
    if "Between" in c:
        b = c["Between"]
        return (f"{describe_field(b.get('Expression'), aliases)['text']} between "
                f"{_literal(b.get('LowerBound'))} and {_literal(b.get('UpperBound'))}")
    if "Contains" in c:
        k = c["Contains"]
        return f"{describe_field(k.get('Left'), aliases)['text']} contains {_literal(k.get('Right'))}"
    return "(condition not recognised)"


def describe_filter_definition(fd: dict) -> str | None:
    if not isinstance(fd, dict) or not fd.get("Where"):
        return None
    aliases = {x.get("Name"): x.get("Entity") for x in fd.get("From") or [] if x.get("Name")}
    return "; ".join(describe_condition(w.get("Condition"), aliases) for w in fd["Where"])


def describe_filters(filters: list) -> list[dict]:
    out = []
    for f in filters or []:
        if not isinstance(f, dict):
            continue
        field = describe_field(f.get("field") or f.get("expression")) if (f.get("field") or f.get("expression")) else None
        out.append({
            "field": field["text"] if field else None, "type": f.get("type"),
            "condition": describe_filter_definition(f.get("filter")),
            "hidden": bool(f.get("isHiddenInViewMode")), "locked": bool(f.get("isLockedInViewMode")),
        })
    return out


def _title(objs: dict) -> str | None:
    for item in (objs or {}).get("title") or []:
        text = (((item or {}).get("properties") or {}).get("text") or {})
        lit = ((text.get("expr") or {}).get("Literal") or {}).get("Value")
        if isinstance(lit, str):
            return lit[1:-1].replace("''", "'") if lit.startswith("'") and lit.endswith("'") else lit
    return None


def _slicer_selection(objs: dict) -> str | None:
    for item in (objs or {}).get("general") or []:
        props = (item or {}).get("properties") or {}
        flt = ((props.get("filter") or {}).get("filter"))
        desc = describe_filter_definition(flt)
        if desc:
            return desc
    for item in (objs or {}).get("data") or []:  # date range slicers keep start/end here
        props = (item or {}).get("properties") or {}
        start, end = props.get("startDate"), props.get("endDate")
        if start or end:
            return f"from {_literal((start or {}).get('expr', {}))} to {_literal((end or {}).get('expr', {}))}"
    return None


SLICERS = {"slicer", "advancedSlicerVisual", "listSlicer", "textSlicer", "buttonSlicer"}
NO_DATA = {"textbox", "image", "shape", "actionButton", "basicShape", "pageNavigator", "bookmarkNavigator"}


def _visual(name, vtype, title, roles, filters, selection=None, hidden=False, pos=None) -> dict:
    return {"name": name, "type": vtype, "title": title, "slicer": vtype in SLICERS, "fields": roles,
            "filters": filters, "selection": selection, "hidden": hidden, "position": pos}


# ---------------------------------------------------------------------------------------------------------------
# Report: PBIR
# ---------------------------------------------------------------------------------------------------------------


def load_pbir(definition: Path, warnings: list[str]) -> dict:
    pages_dir = definition / "pages"
    meta = _read_json(pages_dir / "pages.json", warnings) or {}
    order = meta.get("pageOrder") or []
    folders = [p for p in pages_dir.iterdir() if p.is_dir()] if pages_dir.is_dir() else []
    by_name = {}
    for pf in folders:
        page = _read_json(pf / "page.json", warnings)
        if page is None:
            warnings.append(f"{pf}: no page.json")
            continue
        visuals = []
        vdir = pf / "visuals"
        for vf in sorted(vdir.iterdir()) if vdir.is_dir() else []:
            v = _read_json(vf / "visual.json", warnings)
            if not v:
                continue
            if "visualGroup" in v and "visual" not in v:
                continue
            vis = v.get("visual") or {}
            roles = {}
            for role, state in ((vis.get("query") or {}).get("queryState") or {}).items():
                roles[role] = [_proj(p) for p in (state or {}).get("projections") or []]
            pos = v.get("position") or {}
            visuals.append(_visual(
                v.get("name") or vf.name, vis.get("visualType"), _title(vis.get("visualContainerObjects")),
                roles, describe_filters((v.get("filterConfig") or {}).get("filters")),
                _slicer_selection(vis.get("objects")) if vis.get("visualType") in SLICERS else None,
                bool(v.get("isHidden")), (pos.get("y", 0), pos.get("x", 0))))
        visuals.sort(key=lambda x: x["position"] or (0, 0))
        by_name[page.get("name") or pf.name] = {
            "name": page.get("name") or pf.name, "display_name": page.get("displayName"),
            "hidden": page.get("visibility") == "HiddenInViewMode",
            "filters": describe_filters((page.get("filterConfig") or {}).get("filters")),
            "visuals": visuals,
        }
    names = [n for n in order if n in by_name] + sorted(n for n in by_name if n not in order)
    rep = _read_json(definition / "report.json", warnings) or {}
    return {"format": "PBIR", "pages": [by_name[n] for n in names],
            "filters": describe_filters((rep.get("filterConfig") or {}).get("filters"))}


def _proj(p: dict) -> dict:
    d = describe_field(p.get("field"))
    if p.get("displayName"):
        d["display_name"] = p["displayName"]
    return d


# ---------------------------------------------------------------------------------------------------------------
# Report: PBIR-Legacy (report.json)
# ---------------------------------------------------------------------------------------------------------------


def _json_string(v, where: str, warnings: list[str]):
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    try:
        return json.loads(v)
    except ValueError as e:
        warnings.append(f"{where}: could not read embedded JSON ({e})")
        return None


def load_legacy(path: Path, warnings: list[str]) -> dict:
    rep = _read_json(path, warnings) or {}
    pages = []
    for s in sorted(rep.get("sections") or [], key=lambda s: s.get("ordinal", 0)):
        visuals = []
        for vc in s.get("visualContainers") or []:
            cfg = _json_string(vc.get("config"), f"{path} page {s.get('displayName')}", warnings) or {}
            sv = cfg.get("singleVisual")
            if not sv:
                continue
            pq = sv.get("prototypeQuery") or {}
            aliases = {x.get("Name"): x.get("Entity") for x in pq.get("From") or []}
            selects = {}
            for sel in pq.get("Select") or []:
                d = describe_field(sel, aliases)
                if sel.get("NativeReferenceName"):
                    d["display_name"] = sel["NativeReferenceName"]
                selects[sel.get("Name")] = d
            roles = {}
            for role, items in (sv.get("projections") or {}).items():
                roles[role] = [selects.get(i.get("queryRef"), {"kind": "unknown", "table": None,
                                                               "name": i.get("queryRef"), "text": i.get("queryRef")})
                               for i in items or []]
            vfilters = describe_filters(_json_string(vc.get("filters"), f"{path} visual filters", warnings))
            vtype = sv.get("visualType")
            visuals.append(_visual(
                cfg.get("name"), vtype, _title(sv.get("vcObjects")), roles, vfilters,
                _slicer_selection(sv.get("objects")) if vtype in SLICERS else None, False,
                (vc.get("y", 0), vc.get("x", 0))))
        visuals.sort(key=lambda x: x["position"] or (0, 0))
        pages.append({
            "name": s.get("name"), "display_name": s.get("displayName"),
            "hidden": s.get("visibility") == 1 or bool((_json_string(s.get("config"), "page config", warnings) or {}).get("visibility")),
            "filters": describe_filters(_json_string(s.get("filters"), f"{path} page filters", warnings)),
            "visuals": visuals,
        })
    return {"format": "PBIR-Legacy (report.json)", "pages": pages,
            "filters": describe_filters(_json_string(rep.get("filters"), f"{path} report filters", warnings))}


# ---------------------------------------------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------------------------------------------


def summarise(path: str | Path) -> dict:
    warnings: list[str] = []
    report_dir, model_dir = locate(Path(path), warnings)
    out: dict = {"report_folder": str(report_dir) if report_dir else None,
                 "model_folder": str(model_dir) if model_dir else None,
                 "model": None, "report": None, "warnings": warnings}
    if model_dir:
        if (model_dir / "definition").is_dir():
            model = load_tmdl(model_dir / "definition", warnings)
        elif (model_dir / "model.bim").is_file():
            model = load_bim(model_dir / "model.bim", warnings)
        else:
            model = None
            warnings.append(f"{model_dir}: neither definition/ (TMDL) nor model.bim (TMSL) found")
        if model:
            _enrich_model(model)
            out["model"] = model
    else:
        warnings.append("no semantic model found")
    if report_dir:
        if (report_dir / "definition" / "pages").is_dir():
            out["report"] = load_pbir(report_dir / "definition", warnings)
        elif (report_dir / "report.json").is_file():
            out["report"] = load_legacy(report_dir / "report.json", warnings)
        else:
            warnings.append(f"{report_dir}: neither definition/pages (PBIR) nor report.json found")
        if out["report"]:
            _mark_measures(out["report"], out["model"])
    else:
        warnings.append("no report found")
    return out


def _enrich_model(model: dict) -> None:
    params = m_parameters(model["expressions"])
    model["parameters"] = params
    queries = {e["name"] for e in model["expressions"]}
    for e in model["expressions"]:
        if e["name"] not in params:
            e["source"] = analyse_m(e["expression"], params, queries - {e["name"]})
    for t in model["tables"]:
        for p in t["partitions"]:
            ptype = (p.get("type") or "").lower()
            if ptype == "calculated":
                p["source"] = {"kind": "Calculated table (DAX)"}
                t["calculated_table"] = True
                p["flags"] = dax_flags(p.get("expression") or "")
            elif ptype == "entity":
                p["source"] = {"kind": "Direct Lake / entity", "object": ".".join(
                    x for x in (p.get("schema"), p.get("entity")) if x), "references":
                    [p["expression_source"]] if p.get("expression_source") else []}
            else:
                p["source"] = analyse_m(p.get("expression") or "", params, queries)
        for c in t["columns"]:
            if c["calculated"]:
                c["flags"] = dax_flags(c["expression"] or "")
        for m in t["measures"]:
            m["flags"] = dax_flags(m["expression"])
            m["refs"] = dax_refs(m["expression"])
    for r in model["roles"]:
        for f in r["filters"]:
            f["flags"] = dax_flags(f["expression"])


def _mark_measures(report: dict, model: dict | None) -> None:
    """In PBIR-Legacy a measure reference looks like a column one; fix the kind using the model."""
    if not model:
        return
    measures = {(t["name"], m["name"]) for t in model["tables"] for m in t["measures"]}
    for page in report["pages"]:
        for v in page["visuals"]:
            for fields in v["fields"].values():
                for f in fields:
                    if f.get("kind") == "column" and (f.get("table"), f.get("name")) in measures:
                        f["kind"] = "measure"
                        f["text"] = f"{f['table']}.[{f['name']}]"


# ---------------------------------------------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------------------------------------------


def _indent_block(text: str, pad: str) -> str:
    return "\n".join(pad + ln for ln in (text or "").expandtabs(4).splitlines())


def _flags_text(flags: dict) -> str:
    return "; ".join(f"{k}: {', '.join(v)}" for k, v in flags.items())


def render_text(s: dict) -> str:
    out: list[str] = []
    w = out.append
    w(f"Report folder:         {s['report_folder'] or '-'}")
    w(f"Semantic model folder: {s['model_folder'] or '-'}")
    m = s.get("model")
    if m:
        w(f"Model format: {m['format']}")
        if m.get("parameters"):
            w("\nPARAMETERS")
            for k, v in m["parameters"].items():
                w(f"  {k} = {v}")
        w("\nTABLES AND SOURCES")
        for t in m["tables"]:
            hid = " (hidden)" if t["hidden"] else ""
            kind = " [calculated table]" if t.get("calculated_table") else ""
            kind = " [calculation group]" if t.get("calculation_group") is not None else kind
            w(f"  {t['name']}{hid}{kind}")
            for p in t["partitions"]:
                src = p.get("source") or {}
                bits = [src.get("kind") or "source not recognised"]
                if src.get("object"):
                    bits.append(src["object"])
                if src.get("server"):
                    bits.append(f"server {src['server']}")
                if src.get("location"):
                    bits.append(f"at {src['location']}")
                if src.get("database") and not src.get("object"):
                    bits.append(f"database {src['database']}")
                if src.get("references"):
                    bits.append("uses query " + ", ".join(src["references"]))
                mode = f" ({p['mode']})" if p.get("mode") else ""
                w(f"    source{mode}: " + " | ".join(bits))
                if src.get("native_sql"):
                    w("      native SQL:")
                    w(_indent_block(src["native_sql"], "        "))
                if p.get("type") == "calculated" and p.get("expression"):
                    w(_indent_block(p["expression"], "        "))
            for c in t["columns"]:
                flags = [c["data_type"] or "?"]
                if c["hidden"]:
                    flags.append("hidden")
                if c["calculated"]:
                    flags.append("calculated")
                w(f"    - {c['name']}: {', '.join(flags)}")
                if c["calculated"]:
                    w(_indent_block(c["expression"], "        = "))
                    if c.get("flags"):
                        w(f"        TRANSLATE WITH CARE ({_flags_text(c['flags'])})")
            for ci in t.get("calculation_group") or []:
                w(f"    * calculation item {ci['name']}")
                w(_indent_block(ci["expression"], "        "))
        shared = [e for e in m["expressions"] if e["name"] not in (m.get("parameters") or {})]
        if shared:
            w("\nSHARED QUERIES (expressions)")
            for e in shared:
                src = e.get("source") or {}
                w(f"  {e['name']}: {src.get('kind') or 'not recognised'}"
                  + (f" | {src['object']}" if src.get("object") else "")
                  + (f" | server {src['server']}" if src.get("server") else ""))
        w("\nMEASURES")
        n = 0
        for t in m["tables"]:
            for me in t["measures"]:
                n += 1
                hid = " (hidden)" if me["hidden"] else ""
                fmt = f"  format {me['format']}" if me.get("format") else ""
                w(f"  {t['name']}.[{me['name']}]{hid}{fmt}")
                w(_indent_block(me["expression"], "      "))
                if me["flags"]:
                    w(f"    TRANSLATE WITH CARE ({_flags_text(me['flags'])})")
        if not n:
            w("  (none)")
        w("\nRELATIONSHIPS")
        for r in m["relationships"]:
            card = f"{r['from_cardinality']}-to-{r['to_cardinality']}"
            extra = "" if r["active"] else "  INACTIVE (used through USERELATIONSHIP)"
            if r["from_cardinality"] == "many" and r["to_cardinality"] == "many":
                extra += "  MANY-TO-MANY (check the grain; totals may not add up)"
            w(f"  {r['from_table']}.{r['from_column']} -> {r['to_table']}.{r['to_column']}  "
              f"[{card}, cross-filter {r['cross_filter']}]{extra}")
        if not m["relationships"]:
            w("  (none)")
        w("\nROW-LEVEL SECURITY")
        for r in m["roles"]:
            w(f"  role {r['name']} ({r['permission'] or 'read'}; {r['members']} members in the file)")
            for f in r["filters"]:
                w(f"    {f['table']}: {f['expression']}")
        if not m["roles"]:
            w("  (none)")
    rp = s.get("report")
    if rp:
        w(f"\nREPORT ({rp['format']})")
        for f in rp.get("filters") or []:
            w(f"  report filter: {_filter_text(f)}")
        for i, p in enumerate(rp["pages"], 1):
            hid = " (hidden)" if p["hidden"] else ""
            w(f"\n  Page {i}: {p['display_name']}{hid}")
            for f in p["filters"]:
                w(f"    page filter: {_filter_text(f)}")
            for v in p["visuals"]:
                title = f' "{v["title"]}"' if v.get("title") else ""
                label = "SLICER" if v["slicer"] else v["type"]
                w(f"    - {label}{title}" + (" (hidden)" if v["hidden"] else ""))
                for role, fields in v["fields"].items():
                    w(f"        {role}: " + ", ".join(
                        f["text"] + (f' as "{f["display_name"]}"' if f.get("display_name") else "") for f in fields))
                if v.get("selection"):
                    w(f"        selected: {v['selection']}")
                for f in v["filters"]:
                    w(f"        visual filter: {_filter_text(f)}")
    if s["warnings"]:
        w("\nWARNINGS")
        for x in s["warnings"]:
            w(f"  {x}")
    return "\n".join(out) + "\n"


def _filter_text(f: dict) -> str:
    bits = [f.get("condition") or f"{f.get('field')} (no selection)"]
    if f.get("type"):
        bits.append(f"[{f['type']}]")
    if f.get("hidden"):
        bits.append("hidden")
    if f.get("locked"):
        bits.append("locked")
    return " ".join(bits)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a .pbip file, a .Report or .SemanticModel folder, or a folder holding them")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # report titles can hold emoji; a Windows console defaults to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s = summarise(a.path)
    if a.json:
        for page in (s.get("report") or {}).get("pages") or []:
            for v in page["visuals"]:
                v.pop("position", None)
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_text(s))
    return 0 if (s.get("model") or s.get("report")) else 1


if __name__ == "__main__":
    sys.exit(main())
