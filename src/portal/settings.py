"""Environment settings shared by every dashboard: src/environments.yml."""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

import yaml

def with_local_hosts(cfg: dict, local: Path) -> dict:
    """Applies the hosts in environments.local.yml (gitignored), so a fork's workspace hosts stay out of git."""
    if local.exists():
        for name, spec in ((yaml.safe_load(local.read_text(encoding="utf-8")) or {}).get("environments") or {}).items():
            if name not in cfg["environments"]:
                raise ValueError(f"{local.name}: environment {name!r} is not one of {sorted(cfg['environments'])}")
            cfg["environments"][name]["host"] = str(spec["host"]).strip().lower()
    return cfg


_SRC = Path(__file__).resolve().parent.parent
_CFG = with_local_hosts(yaml.safe_load((_SRC / "environments.yml").read_text(encoding="utf-8")),
                        _SRC / "environments.local.yml")
ENVIRONMENTS: dict[str, dict] = _CFG["environments"]
CATALOGS: dict[str, dict] = _CFG["catalogs"]
SECTIONS: list[str] = _CFG["sections"]
# Who may open a dashboard marked `status: draft`, besides the dashboard's own `groups`.
DRAFTS_GROUPS: list[str] = [str(g) for g in (_CFG["drafts_groups"] if "drafts_groups" in _CFG else ["lakeboard-admins"]) or []]
# Catalogs whose data never changes (the freshness label gives their tables no time). Holds each name and, for an
# allowed catalog, its dev and test names too, because /sources sees the SQL after the catalog swap.
STATIC_CATALOGS: frozenset[str] = frozenset(
    n.lower() for c in (_CFG.get("static_catalogs") or [])
    for n in [str(c), *(str(v) for v in (_CFG["catalogs"].get(c) or {}).values())])
LIBS: dict[str, dict] = _CFG.get("libs") or {}
IMAGE_HOSTS: list[str] = _CFG.get("image_hosts") or []
WARM: dict = _CFG.get("warm") or {}
USAGE_TABLES: dict[str, str] = _CFG.get("usage_table") or {}
BRAND: dict = {"name": "LakeBoard", "logo": "/static/brand/logo.svg", **(_CFG.get("brand") or {})}
LOCALE: str = str(_CFG.get("locale") or "en-US")
TIMEZONE: str = str(WARM.get("timezone") or "UTC")  # IANA zone for date defaults, warm times and the freshness label
DATE_TOKENS = ("@today", "@week_start", "@week_end")  # allowed as the default of a DATE parameter


def now_local() -> dt.datetime:
    """Now in the portal's timezone (warm.timezone in src/environments.yml; UTC when not set)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(TIMEZONE))
    except Exception:  # no timezone database on this machine (pip install tzdata)
        return dt.datetime.now(dt.timezone.utc) if TIMEZONE.upper() == "UTC" else dt.datetime.now()


def resolve_default(value):
    """Turns @today / @week_start (Monday) / @week_end (Friday) into a date; other values pass through."""
    if value not in DATE_TOKENS:
        return value
    today = now_local().date()
    monday = today - dt.timedelta(days=today.weekday())
    return str({"@today": today, "@week_start": monday, "@week_end": monday + dt.timedelta(days=4)}[value])


def is_deployed(environ=None) -> bool:
    """True inside Databricks Apps, which sets these variables for every app. Local runs don't have them."""
    environ = os.environ if environ is None else environ
    return any(environ.get(k) for k in ("DATABRICKS_APP_NAME", "DATABRICKS_APP_URL", "DATABRICKS_APP_PORT"))


def is_local_run(environ=None) -> bool:
    """A developer's own run (scripts/run_local.*): a CLI profile stands in for the user token, and not deployed."""
    environ = os.environ if environ is None else environ
    return bool(environ.get("PORTAL_LOCAL_PROFILE")) and not is_deployed(environ)


def normalise_host(value: str | None = None, environ=None) -> str:
    """Workspace host, lowercased, with any leading http(s):// and trailing slashes removed."""
    if value is None:
        environ = os.environ if environ is None else environ
        value = environ.get("DATABRICKS_HOST", "")
    return re.sub(r"^https?://|/+$", "", (value or "").strip().lower())


def _https_origin(value: str) -> str:
    """https://host or https://host:port, with no path, userinfo, query, fragment or wildcard."""
    from urllib.parse import urlparse
    if "*" in value:
        raise ValueError(
            f"FRAME_ANCESTORS entry {value!r} must be an https origin (https://host or https://host:port), with no path or wildcard"
        )
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
    ):
        raise ValueError(
            f"FRAME_ANCESTORS entry {value!r} must be an https origin (https://host or https://host:port), with no path or wildcard"
        )
    host = parsed.hostname
    return f"https://{host}:{parsed.port}" if parsed.port else f"https://{host}"


def frame_ancestors(environ=None) -> list[str]:
    """'self', then https://DATABRICKS_HOST if set, then FRAME_ANCESTORS. Raises on a bad entry."""
    environ = os.environ if environ is None else environ
    origins = ["'self'"]
    host = normalise_host(environ=environ)
    if host:
        origins.append(f"https://{host}")
    raw = (environ.get("FRAME_ANCESTORS") or "").strip()
    if raw:
        for entry in re.split(r"[,\s]+", raw):
            if not entry:
                continue
            origin = _https_origin(entry)
            if origin not in origins:
                origins.append(origin)
    return origins


def x_frame_options(ancestors: list[str] | None = None, environ=None) -> str | None:
    """SAMEORIGIN only when the app may not be framed by any other origin."""
    if ancestors is None:
        ancestors = frame_ancestors(environ)
    return "SAMEORIGIN" if ancestors == ["'self'"] else None


def current_env() -> str:
    """PORTAL_ENV if set, else the environment whose host matches DATABRICKS_HOST. Prod only when both are unset;
    a host that matches nothing raises rather than silently reading prod."""
    env = os.getenv("PORTAL_ENV", "").strip().lower()
    if env:
        if env not in ENVIRONMENTS:
            raise ValueError(f"PORTAL_ENV={env!r} is not one of {sorted(ENVIRONMENTS)}")
        return env
    host = normalise_host()
    for name, spec in ENVIRONMENTS.items():
        if host and host == spec["host"]:
            return name
    if host:
        raise ValueError(f"DATABRICKS_HOST={host!r} matches no host in src/environments.yml; fix the host or set PORTAL_ENV")
    return "prod"


def localise_sql(sql: str, env: str) -> str:
    """Swaps each allowed prod catalog for this environment's catalog."""
    for prod_name, per_env in CATALOGS.items():
        target = per_env.get(env, prod_name)
        if target != prod_name:
            sql = re.sub(rf"\b{re.escape(prod_name)}\.", f"{target}.", sql)
    return sql
