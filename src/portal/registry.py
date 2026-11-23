"""Discovers dashboards: src/dashboards/<slug>/dashboard.yml + index.html + sql/*.sql."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .settings import CATALOGS, DATE_TOKENS, ENVIRONMENTS, LIBS, SECTIONS, current_env, localise_sql

DASHBOARDS_DIR = Path(__file__).resolve().parent.parent / "dashboards"
REVIEWED_PAGES = DASHBOARDS_DIR.parent / "reviewed_pages.yml"  # reviewed page code, by digest (decision 0018)
SHARED_APPROVALS = DASHBOARDS_DIR.parent / "shared_cache.yml"  # reviewed viewer-independent SQL (decision 0018)
TEXT_ASSETS = {".js", ".css", ".svg"}  # hashed as text with LF line endings, like index.html
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DATASET_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PARAM_RE = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")  # :name, not ::cast
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|CALL|COPY|OPTIMIZE|VACUUM|REFRESH|SET|USE)\b",
    re.IGNORECASE,
)
TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)*)", re.IGNORECASE)
CTE_RE = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE)
TABLE_FUNCTIONS = {"LATERAL", "VALUES", "UNNEST", "EXPLODE", "RANGE"}
REMOTE_SCRIPT_RE = re.compile(r"<script[^>]+src\s*=\s*[\"']?(?:https?:)?//", re.IGNORECASE)
PARAM_TYPES = {"STRING", "INT", "BIGINT", "DOUBLE", "DECIMAL", "DATE", "TIMESTAMP", "BOOLEAN"}
GENIE_SPACE_RE = re.compile(r"^[0-9a-f]{32}$")  # Genie space ids are 32 lowercase hex characters
GENIE_KEYS = {"space_id", "sample_questions", "about"}
GENIE_MAX_SAMPLES = 5
GENIE_MAX_SAMPLE_LEN = 200
GENIE_MAX_ABOUT_LEN = 600
SOURCE_MAX_LEN = 200  # `source:` on a dataset: a short note on how its source tables are built
PAGE_KINDS = ("lakeboard", "artifact")  # `page:`; artifact = a Claude Dashboard artifact, run as-is (decision 0011)
STATUSES = ("live", "draft")  # `status:`; draft = only drafts_groups and the dashboard's groups see it
# Files a `page: artifact` dashboard may keep in assets/: scripts, styles, images and fonts. Nothing else is served.
ASSET_TYPES = {
    ".js": "text/javascript", ".css": "text/css",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".svg": "image/svg+xml", ".avif": "image/avif", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
}
ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$")  # flat: no folders, no "..", no leading dot
ASSET_MAX_BYTES = 5_000_000
SNAPSHOT_RE = re.compile(r"^snapshots/[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.json$")
# <script src="x"> / <link href="x"> naming a file by bare name, which a page: artifact dashboard serves from assets/
BARE_REF_RE = re.compile(r"<(?:script|link)\b[^>]*?\s(?:src|href)\s*=\s*[\"']?(?:\./)?([A-Za-z0-9][^\"'\s>/:?#]*)[\"'\s>?#]", re.IGNORECASE)


@dataclass(frozen=True)
class Approvals:
    """What the data team has reviewed: page code (src/reviewed_pages.yml) and shared SQL (src/shared_cache.yml).

    Keys are `<slug>` for index.html, `<slug>/assets/<file>` for an artifact page's files, and `<slug>/<dataset>`
    for SQL. Values are SHA-256 digests (`digest()`), so any edit needs a new review."""
    pages: dict
    shared: dict


def digest(path: Path) -> str:
    """SHA-256 of a page, SQL or text asset as UTF-8 text with LF line endings (read_text turns CRLF into LF, so a
    Windows checkout gets the same digest); other assets (images, fonts) as raw bytes."""
    if path.suffix.lower() in {".html", ".sql"} | TEXT_ASSETS:
        return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_approvals() -> Approvals:
    """Both approval files. A missing or malformed file stops loading: the gate never fails open."""
    out = []
    for path in (REVIEWED_PAGES, SHARED_APPROVALS):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
        if data is None:
            data = {}
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise ValueError(f"src/{path.name} must map names to SHA-256 digests")
        out.append(data)
    return Approvals(pages=out[0], shared=out[1])


def parse_ttl(value: str | int | None, default: int = 3600) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(value))
    if not m:
        raise ValueError(f"bad cache_ttl {value!r}")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def strip_sql_comments_and_strings(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"'(?:[^'\\]|\\.|'')*'|`[^`]*`", " ", sql)


def tables_in(sql: str) -> list[str]:
    """The catalog.schema.table names a dataset's SQL reads (comments, strings and CTE names ignored)."""
    names = set()
    for first, rest in TABLE_RE.findall(strip_sql_comments_and_strings(sql)):
        parts = [first] + [x for x in rest.split(".") if x]
        if len(parts) == 3:
            names.add(".".join(parts).lower())
    return sorted(names)


def table_errors(body: str) -> list[str]:
    """Every table must be catalog.schema.table in an allowed catalog (CTE names excepted)."""
    ctes = {c.lower() for c in CTE_RE.findall(body)}
    errors = []
    for first, rest in TABLE_RE.findall(body):
        parts = [first] + [x for x in rest.split(".") if x]
        name = ".".join(parts)
        if len(parts) == 1:
            if first.lower() not in ctes and first.upper() not in TABLE_FUNCTIONS:
                errors.append(f"table {name!r} is not a CTE in this query; write it as catalog.schema.table")
        elif len(parts) != 3:
            errors.append(f"table {name!r} must be written as catalog.schema.table")
        elif first not in CATALOGS:
            errors.append(f"catalog {first!r} is not allowed (allowed: {sorted(CATALOGS)}; see src/environments.yml)")
    return errors


@dataclass
class Dataset:
    id: str
    title: str
    sql: str
    params: list[str]
    cache_ttl: int
    auth: str  # "user" | "app"
    description: str = ""
    groups: list[str] = field(default_factory=list)  # [] = everyone who can open the dashboard
    shared: bool = False  # one cached result for every viewer (only for data everyone may see)
    warm: list[dict] = field(default_factory=list)  # parameter sets refreshed in the background
    background: bool = True  # auth: app only: keep it refreshed all day (False = load when someone opens the page)
    source: str = ""  # optional plain-text note on how the source is built, shown in the freshness panel
    todo: bool = False  # not connected yet (e.g. imported from a Claude artifact): never queried, see snapshot
    snapshot: str = ""  # todo only: snapshots/<id>.json, served instead in a local preview run (gitignored)
    warm_at: str = "schedule"  # schedule includes app startup; startup runs once per process
    data_through: str = ""  # optional DATE result column: latest event day present in this result
    refresh: str = "changed"  # "always" for queries with dependencies beyond their source tables

    @property
    def cache_kind(self) -> str:
        """How the result is cached, for the freshness panel: user, shared, warm (shared + warm list) or app."""
        if self.todo:
            return "todo"
        if self.auth == "app":
            return "app"
        if self.warm:
            return "warm"
        return "shared" if self.shared else "user"


@dataclass
class Genie:
    """The `genie:` block of dashboard.yml: which Genie space answers questions about this dashboard."""
    space_ids: dict[str, str]  # environment -> space id; an environment without one shows no chat bar
    sample_questions: list[str] = field(default_factory=list)
    about: str = ""


def parse_genie(spec, datasets: dict[str, Dataset]) -> tuple[Genie | None, list[str]]:
    """Validates the `genie:` block. Returns (Genie or None, errors)."""
    if spec is None:
        return None, []
    if not isinstance(spec, dict):
        return None, ["genie: must be a block with space_id (and optionally sample_questions and about)"]
    errors = [f"genie: unknown setting {k!r} (allowed: {sorted(GENIE_KEYS)})" for k in spec if k not in GENIE_KEYS]
    app_sets = sorted(k for k, ds in datasets.items() if ds.auth == "app")
    if app_sets:
        errors.append(f"genie: not allowed on a dashboard with auth: app datasets ({', '.join(app_sets)}); "
                      "Genie answers as the viewer, who may not be able to read that data")
    ids = spec.get("space_id")
    space_ids: dict[str, str] = {}
    if not isinstance(ids, dict) or not ids:
        errors.append("genie: space_id must list the space id per environment, e.g. space_id: {prod: <32 hex characters>}")
    else:
        for env, sid in ids.items():
            if env not in ENVIRONMENTS:
                errors.append(f"genie: space_id environment {env!r} must be one of {sorted(ENVIRONMENTS)}")
            elif sid is None or sid == "":
                continue  # written out but empty = no chat bar in that environment
            elif not isinstance(sid, str) or not GENIE_SPACE_RE.match(sid):
                errors.append(f"genie: space_id for {env} must be 32 lowercase hex characters in quotes (the id in the Genie space URL)")
            else:
                space_ids[env] = sid
    samples = spec.get("sample_questions") or []
    if not isinstance(samples, list) or not all(isinstance(q, str) and q.strip() for q in samples):
        errors.append("genie: sample_questions must be a list of questions (text)")
        samples = []
    elif len(samples) > GENIE_MAX_SAMPLES:
        errors.append(f"genie: at most {GENIE_MAX_SAMPLES} sample_questions")
    elif any(len(q) > GENIE_MAX_SAMPLE_LEN for q in samples):
        errors.append(f"genie: each sample question must be under {GENIE_MAX_SAMPLE_LEN} characters")
    about = spec.get("about") or ""
    if not isinstance(about, str):
        errors.append("genie: about must be text")
        about = ""
    elif len(about) > GENIE_MAX_ABOUT_LEN:
        errors.append(f"genie: about must be under {GENIE_MAX_ABOUT_LEN} characters")
    if errors:
        return None, errors
    return Genie(space_ids=space_ids, sample_questions=[q.strip() for q in samples], about=" ".join(about.split())), []


@dataclass
class Dashboard:
    slug: str
    title: str
    description: str
    owner: str
    groups: list[str]
    order: int
    datasets: dict[str, Dataset]
    params: dict[str, dict]
    page: str
    path: Path
    section: str = "Other"
    environments: list[str] = field(default_factory=lambda: list(ENVIRONMENTS))
    libs: list[str] = field(default_factory=list)
    replaces: str = ""
    errors: list[str] = field(default_factory=list)
    genie: Genie | None = None
    page_kind: str = "lakeboard"  # `page:` lakeboard (default) or artifact
    status: str = "live"  # `status:` live (default) or draft
    assets: dict[str, Path] = field(default_factory=dict)  # page: artifact only; name -> file in assets/
    warnings: list[str] = field(default_factory=list)  # reported by check.py; they don't stop the dashboard loading
    unreviewed: list[str] = field(default_factory=list)  # the review errors (also in errors); a local run allows them

    @property
    def draft(self) -> bool:
        return self.status == "draft"

    def genie_space(self, env: str) -> str | None:
        """The Genie space for this environment, or None (no chat bar)."""
        return self.genie.space_ids.get(env) if self.genie else None

    def catalogue_entry(self) -> dict:
        return {"slug": self.slug, "title": self.title, "description": self.description, "owner": self.owner,
                "section": self.section}


def load_dashboard(folder: Path, env: str | None = None, approvals: Approvals | None = None) -> Dashboard:
    """One dashboard. A folder under src/dashboards/ is checked against the approval files (decision 0018); a test
    dashboard elsewhere only when `approvals` is passed."""
    env = env or current_env()
    if approvals is None and folder.parent.resolve() == DASHBOARDS_DIR.resolve():
        approvals = load_approvals()
    slug = folder.name
    errors: list[str] = []
    warnings: list[str] = []
    unreviewed: list[str] = []
    if not SLUG_RE.match(slug):
        errors.append(f"folder name {slug!r} must be lowercase letters, digits and hyphens")
    manifest = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8")) or {}
    params = manifest.get("params") or {}
    for name, spec in params.items():
        ptype = str((spec or {}).get("type", "STRING")).upper()
        if ptype not in PARAM_TYPES:
            errors.append(f"param {name}: type must be one of {sorted(PARAM_TYPES)}")
        default = (spec or {}).get("default")
        if isinstance(default, str) and default.startswith("@") and (default not in DATE_TOKENS or ptype != "DATE"):
            errors.append(f"param {name}: default {default!r} must be one of {list(DATE_TOKENS)} on a DATE parameter")
    datasets: dict[str, Dataset] = {}
    for ds_id, spec in (manifest.get("datasets") or {}).items():
        if not DATASET_RE.match(ds_id):
            errors.append(f"dataset id {ds_id!r} is invalid")
            continue
        sql_path = folder / spec["sql"]
        if not sql_path.is_file():
            errors.append(f"dataset {ds_id}: {spec['sql']} not found")
            continue
        todo = spec.get("todo", False)
        if not isinstance(todo, bool):
            errors.append(f"dataset {ds_id}: todo must be true or false")
            todo = False
        snapshot = spec.get("snapshot") or ""
        if snapshot and not todo:
            errors.append(f"dataset {ds_id}: snapshot is only used with todo: true")
        elif snapshot and (not isinstance(snapshot, str) or not SNAPSHOT_RE.match(snapshot)):
            errors.append(f"dataset {ds_id}: snapshot must be snapshots/<name>.json (letters, digits, - and _)")
            snapshot = ""
        if todo:
            warnings.append(f"dataset {ds_id} is todo: it is not connected to Databricks yet; write its SQL and remove "
                            "todo: true before it can load")
        sql = sql_path.read_text(encoding="utf-8").strip().rstrip(";")
        body = strip_sql_comments_and_strings(sql)
        if todo and not body.strip():
            pass  # a todo dataset's SQL may be a stub with comments only
        elif not re.match(r"\s*(WITH|SELECT)\b", body, re.IGNORECASE):
            errors.append(f"dataset {ds_id}: SQL must start with SELECT or WITH")
        if ";" in body:
            errors.append(f"dataset {ds_id}: SQL must be a single statement")
        bad = FORBIDDEN.search(body)
        if bad:
            errors.append(f"dataset {ds_id}: SQL contains {bad.group(1).upper()}")
        errors += [f"dataset {ds_id}: {e}" for e in table_errors(body)]
        used = sorted(set(PARAM_RE.findall(body)))
        undeclared = [p for p in used if p not in params]
        if undeclared:
            errors.append(f"dataset {ds_id}: parameters {undeclared} are not declared under params")
        auth = spec.get("auth", "user")
        if auth not in ("user", "app"):
            errors.append(f"dataset {ds_id}: auth must be user or app")
        if auth == "app" and (not manifest.get("groups") or not spec.get("groups")):
            errors.append(f"dataset {ds_id}: auth: app needs explicit groups on the dashboard and on the dataset, "
                          "because the data is read as the app, not as the viewer")
        if auth == "app" and used:
            errors.append(f"dataset {ds_id}: auth: app datasets cannot take parameters")
        cache = spec.get("cache", "user")
        if cache not in ("user", "shared"):
            errors.append(f"dataset {ds_id}: cache must be user or shared")
        if approvals is not None and auth == "user" and cache == "shared" and not todo                 and approvals.shared.get(f"{slug}/{ds_id}") != digest(sql_path):
            unreviewed.append(f"dataset {ds_id}: cache: shared needs a review of its SQL recorded in src/shared_cache.yml "
                              f"(python scripts/approve.py {slug})")
        warm = list(spec.get("warm") or [])
        if warm and cache != "shared":
            errors.append(f"dataset {ds_id}: warm needs cache: shared")
        warm_at = spec.get("warm_at", "schedule")
        if warm_at not in ("schedule", "startup"):
            errors.append(f"dataset {ds_id}: warm_at must be schedule or startup")
        if "warm_at" in spec and not warm:
            errors.append(f"dataset {ds_id}: warm_at needs a warm parameter list")
        for entry in warm:
            unknown = [k for k in (entry or {}) if k not in used] if isinstance(entry, dict) else [entry]
            if unknown:
                errors.append(f"dataset {ds_id}: warm entry uses {unknown}, which the SQL does not take as parameters")
        source = "" if spec.get("source") is None else spec.get("source")
        if not isinstance(source, str):
            errors.append(f"dataset {ds_id}: source must be text")
            source = ""
        elif len(source) > SOURCE_MAX_LEN:
            errors.append(f"dataset {ds_id}: source must be at most {SOURCE_MAX_LEN} characters")
        data_through = spec.get("data_through", "")
        if not isinstance(data_through, str) or (data_through and not re.fullmatch(r"[A-Za-z_]\w*", data_through)):
            errors.append(f"dataset {ds_id}: data_through must name a DATE result column")
            data_through = ""
        refresh = spec.get("refresh", "changed")
        if refresh not in ("changed", "always"):
            errors.append(f"dataset {ds_id}: refresh must be changed or always")
            refresh = "changed"
        datasets[ds_id] = Dataset(
            id=ds_id, title=spec.get("title", ds_id), description=spec.get("description", ""), sql=localise_sql(sql, env),
            params=used, cache_ttl=parse_ttl(spec.get("cache_ttl")), auth=auth, groups=list(spec.get("groups") or []),
            shared=cache == "shared" or auth == "app", warm=[w for w in warm if isinstance(w, dict)],
            background=bool(spec.get("background", True)), source=" ".join(source.split()),
            todo=todo, snapshot=snapshot if todo else "",
            warm_at=warm_at,
            data_through=data_through,
            refresh=refresh,
        )
    page_path = folder / "index.html"
    page = page_path.read_text(encoding="utf-8") if page_path.is_file() else ""
    if not page:
        errors.append("index.html is missing")
    page_kind = manifest.get("page", "lakeboard")
    if page_kind not in PAGE_KINDS:
        errors.append(f"page must be one of {list(PAGE_KINDS)}")
    status = manifest.get("status", "live")
    if status not in STATUSES:
        errors.append(f"status must be one of {list(STATUSES)}")
    assets, asset_errors = load_assets(folder, page_kind == "artifact")
    errors += asset_errors
    if approvals is not None:
        reviewed = {"index.html": (slug, page_path)} if page else {}
        reviewed.update({f"assets/{n}": (f"{slug}/assets/{n}", p) for n, p in assets.items()})
        for name, (key, path) in reviewed.items():
            if approvals.pages.get(key) != digest(path):
                unreviewed.append(f"{name} has no matching review in src/reviewed_pages.yml (python scripts/approve.py {slug})")
    errors += unreviewed
    scripts = {"index.html": page}
    scripts.update({f"assets/{n}": p.read_text(encoding="utf-8", errors="replace") for n, p in assets.items() if n.endswith(".js")})
    calc_ids = {c for text in scripts.values() for c in re.findall(r"dash\.calc\(\s*['\"]([A-Za-z0-9_-]+)['\"]", text)}
    for name, text in scripts.items():
        for ds_id in sorted(set(re.findall(r"dash\.(?:data|refresh)\(\s*['\"]([A-Za-z0-9_-]+)['\"]", text))):
            if ds_id not in datasets and ds_id not in calc_ids:
                errors.append(f"{name} reads dataset {ds_id!r}, which dashboard.yml does not declare")
        if REMOTE_SCRIPT_RE.search(text):
            errors.append(f"{name} loads a script from another site; use `libs:` or ask the data team to add the library")
    if page_kind == "artifact":
        for ref in sorted(set(BARE_REF_RE.findall(page))):
            if ref not in assets:
                errors.append(f"index.html loads {ref!r}, which is not in assets/")
    section = manifest.get("section", "Other")
    if section not in SECTIONS:
        errors.append(f"section {section!r} must be one of {SECTIONS} (new sections are added in src/environments.yml)")
    envs = list(manifest.get("environments") or ENVIRONMENTS)
    for e in envs:
        if e not in ENVIRONMENTS:
            errors.append(f"environments: {e!r} must be one of {sorted(ENVIRONMENTS)}")
    libs = list(manifest.get("libs") or [])
    for lib in libs:
        if lib not in LIBS:
            errors.append(f"libs: {lib!r} must be one of {sorted(LIBS)}")
    genie, genie_errors = parse_genie(manifest.get("genie"), datasets)
    errors += genie_errors
    return Dashboard(
        slug=slug, title=manifest.get("title", slug), description=manifest.get("description", ""),
        owner=manifest.get("owner", ""), groups=list(manifest.get("groups") or []), order=int(manifest.get("order", 100)),
        datasets=datasets, params=params, page=page, path=folder, section=section, environments=envs, libs=libs,
        replaces=str(manifest.get("replaces", "")), errors=errors, genie=genie,
        page_kind=page_kind if page_kind in PAGE_KINDS else "lakeboard",
        status=status if status in STATUSES else "draft",  # an unreadable status is treated as the safer one
        assets=assets, warnings=warnings, unreviewed=unreviewed,
    )


def load_assets(folder: Path, allowed: bool) -> tuple[dict[str, Path], list[str]]:
    """The files in <dashboard>/assets/: flat, known types only, no links. Only page: artifact dashboards have them."""
    root = folder / "assets"
    if not root.exists() and not root.is_symlink():
        return {}, []
    if not allowed:
        return {}, ["assets/ is only used by page: artifact dashboards; put the page's code in index.html"]
    if root.is_symlink() or not root.is_dir():
        return {}, ["assets must be a plain folder"]
    assets, errors = {}, []
    for p in sorted(root.iterdir()):
        name = p.name
        if p.is_symlink() or not p.is_file():
            errors.append(f"assets/{name}: only plain files are allowed (no folders or links)")
        elif not ASSET_NAME_RE.match(name):
            errors.append(f"assets/{name}: file names may use letters, digits, '-', '_' and '.' only")
        elif p.suffix.lower() not in ASSET_TYPES:
            errors.append(f"assets/{name}: only {', '.join(sorted(ASSET_TYPES))} files are allowed")
        elif p.stat().st_size > ASSET_MAX_BYTES:
            errors.append(f"assets/{name}: larger than {ASSET_MAX_BYTES // 1_000_000} MB")
        else:
            assets[name] = p
    return assets, errors


def load_all(root: Path = DASHBOARDS_DIR, env: str | None = None) -> dict[str, Dashboard]:
    """Every dashboard, valid or not, in navigation order. Callers filter on .errors and .environments."""
    approvals = load_approvals() if root.resolve() == DASHBOARDS_DIR.resolve() else None
    boards = {}
    for folder in sorted(p for p in root.iterdir() if (p / "dashboard.yml").is_file()):
        d = load_dashboard(folder, env, approvals)
        boards[d.slug] = d
    rank = {s: i for i, s in enumerate(SECTIONS)}
    return dict(sorted(boards.items(), key=lambda kv: (rank.get(kv[1].section, 99), kv[1].order, kv[1].title)))
