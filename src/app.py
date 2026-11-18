"""LakeBoard: one Databricks App serving many git-managed dashboards. See docs/DESIGN.md."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from portal import access, data, genie, snapshots, sources, usage, xlsx
from portal.auth import LOCAL_PROFILE, User, can_open, can_open_dashboard, current_user
from portal.registry import ASSET_TYPES, Dashboard, load_all
from portal.settings import (BRAND, DRAFTS_GROUPS, IMAGE_HOSTS, LIBS, LOCALE, SECTIONS, TIMEZONE, WARM, current_env,
                             is_local_run, resolve_default)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("portal")
HERE = Path(__file__).resolve().parent
TEMPLATES = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "templates").glob("*.html")}
ENV = current_env()
sources.load_map(ENV)  # deploy-time view map for the freshness label, if built for this environment
VERSION = str(int(time.time()))  # added to static URLs so browsers pick up new files after a deploy

# Pages run with the viewer's data access, so the browser may only talk to this app (plus fonts and map tiles).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob: " + " ".join(IMAGE_HOSTS),
    "connect-src 'self'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
])


def render(name: str, **values: str) -> str:
    """Fills [[name]] placeholders. Page HTML goes in last, as-is, since it contains its own braces and $."""
    out = TEMPLATES[name]
    page = values.pop("page", None)
    for k, v in values.items():
        out = out.replace(f"[[{k}]]", v)
    return out.replace("[[page]]", page) if page is not None else out


DASHBOARDS = load_all(env=ENV)
for d in DASHBOARDS.values():
    for err in d.errors:
        log.error("dashboard %s: %s", d.slug, err)
LIVE = {k: v for k, v in DASHBOARDS.items() if not v.errors and ENV in v.environments}
LOCAL_RUN = is_local_run()  # a developer's own run: drafts are shown to them (decision 0011)
PREVIEW_SNAPSHOTS = snapshots.preview_enabled()  # local only: todo datasets serve their snapshot rows
if PREVIEW_SNAPSHOTS:
    log.warning("snapshot preview is on: todo datasets serve rows from their local snapshots/ file, not Databricks")
log.info("environment %s: %d dashboards live, %d hidden or broken", ENV, len(LIVE), len(DASHBOARDS) - len(LIVE))


def app_client() -> WorkspaceClient:
    return WorkspaceClient(profile=LOCAL_PROFILE) if LOCAL_PROFILE else WorkspaceClient()


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(data.warm_datasets(LIVE, app_client, ENV)),
             asyncio.create_task(usage.flush_loop(app_client, data.WAREHOUSE_ID, ENV))]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title=str(BRAND["name"]), lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Send only our origin (never the path) to other sites. OpenStreetMap blocks tile requests that carry no referrer.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def board_for(request: Request, slug: str) -> tuple[Dashboard, User]:
    d = LIVE.get(slug)
    if not d:
        raise HTTPException(404, "Dashboard not found")
    user = current_user(request)
    if not may_open(user, d):
        raise HTTPException(403, "You don't have access to this dashboard")
    return d, user


def may_open(user: User, d: Dashboard) -> bool:
    """Dashboard groups, plus drafts_groups for a `status: draft` dashboard (portal.auth.can_open_dashboard)."""
    return can_open_dashboard(user, d, DRAFTS_GROUPS, local=LOCAL_RUN)


DRAFT_BADGE = '<span class="pn-draft" title="Draft: not published yet; only some groups can see it">Draft</span>'


def nav_html(user: User, active: str | None) -> str:
    """Left navigation: one block per section, listing the dashboards this user may open."""
    out = []
    for section in SECTIONS:
        items = [d for d in LIVE.values() if d.section == section and may_open(user, d)]
        if not items:
            continue
        links = ""
        for d in items:
            current = ' aria-current="page"' if d.slug == active else ""
            badge = DRAFT_BADGE if d.draft else ""
            links += f'<li><a href="/d/{d.slug}"{current} title="{html.escape(d.description)}">{html.escape(d.title)}{badge}</a></li>'
        out.append(f'<div class="pn-section"><h2>{html.escape(section)}</h2><ul>{links}</ul></div>')
    return "\n".join(out) or '<p class="pn-empty">No dashboards are shared with you yet.</p>'


# The freshness label and refresh controls. Not shown on the home page.
REFRESH_HTML = (
    '<div class="pn-fresh-wrap">'
    '<button type="button" class="pn-fresh" id="pn-fresh" aria-expanded="false" aria-controls="pn-fresh-panel" hidden>'
    '<span class="pn-fresh-long"></span><span class="pn-fresh-short"></span></button>'
    '<div class="pn-fresh-panel" id="pn-fresh-panel" role="dialog" aria-label="How fresh this data is" tabindex="-1" hidden></div>'
    '</div>'
    '<div class="pn-refresh-actions">'
    '<button type="button" class="pn-refresh" onclick="dash.refreshChanged()">Refresh data</button>'
    '<button type="button" class="pn-refresh" onclick="dash.refreshAll()">Refresh all</button>'
    '<span class="pn-refresh-status" id="pn-refresh-status" role="status"></span>'
    '</div>'
)


def shell(user: User, *, title: str, active: str | None, config: dict, page: str, libs: list[str] = (),
          artifact: bool = False) -> str:
    css = "".join(f'<link rel="stylesheet" href="{u}">' for lib in libs for u in LIBS[lib].get("css", []))
    js = "".join(f'<script src="{u}"></script>' for lib in libs for u in LIBS[lib].get("js", []))
    if artifact:  # a Claude Dashboard artifact: its tokens, then the runtime that mounts and runs the page
        css += f'<link rel="stylesheet" href="/static/artifact.css?v={VERSION}">'
        js += f'<script src="/static/artifact.js?v={VERSION}" defer></script>'
    if config.get("genie"):  # the Ask Genie bar, only on dashboards with a Genie space in this environment
        css += f'<link rel="stylesheet" href="/static/genie.css?v={VERSION}">'
        js += f'<script src="/static/genie.js?v={VERSION}" defer></script>'
    badge = "" if ENV == "prod" else f'<span class="pn-env" title="Reads {ENV} data">{ENV.upper()}</span>'
    config = {**config, "locale": LOCALE, "tz": TIMEZONE}
    return render(
        "shell", title=html.escape(title), brand=html.escape(str(BRAND["name"])), logo=html.escape(str(BRAND["logo"])), user=html.escape(user.email), nav=nav_html(user, active), env_badge=badge,
        libs_css=css, libs_js=js, v=VERSION, home_current=' aria-current="page"' if active is None else "",
        refresh="" if active is None else REFRESH_HTML,
        config=json.dumps(config).replace("</", "<\\/"), page=page,
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    blocks = []
    for section in SECTIONS:
        cards = "".join(
            f'<a class="pc-card" href="/d/{d.slug}"><span class="pc-owner">{html.escape(d.owner)}</span>'
            f"<strong>{html.escape(d.title)}{DRAFT_BADGE if d.draft else ''}</strong><span>{html.escape(d.description)}</span></a>"
            for d in LIVE.values() if d.section == section and may_open(user, d)
        )
        if cards:
            blocks.append(f'<section><h2 class="pc-h">{html.escape(section)}</h2><div class="pc-grid">{cards}</div></section>')
    body = "\n".join(blocks) or '<p class="pc-empty">No dashboards are shared with you yet.</p>'
    page = f'<div class="pc-home"><h1>Dashboards</h1><p class="pc-lede">Pick a dashboard from the menu, or from the tiles below.</p>{body}</div>'
    usage.record("home", ENV, user.email)
    return shell(user, title="Dashboards", active=None, config={"slug": None, "datasets": {}, "params": {}}, page=page)


@app.get("/d/{slug}", response_class=HTMLResponse)
def dashboard_page(request: Request, slug: str):
    d, user = board_for(request, slug)
    config = {
        "slug": d.slug, "title": d.title, "env": ENV,
        "datasets": {k: {"title": v.title, "description": v.description, "params": v.params,
                         "allowed": can_open(user, v.groups), "cache": v.cache_kind, "source": v.source}
                     for k, v in d.datasets.items()},
        "params": {k: resolve_default((v or {}).get("default")) for k, v in d.params.items()},
    }
    if ENV in WARM.get("environments", []):  # when warm datasets are pre-loaded, for the freshness panel
        config["warm_times"] = list(WARM.get("times", []))
    if d.genie_space(ENV):
        config["genie"] = {"samples": d.genie.sample_questions}
    page = d.page.replace("{{LOGO}}", html.escape(str(BRAND["logo"])))
    if d.page_kind == "artifact":
        # The page goes in inert, inside a <template>: nothing in it loads or runs until static/artifact.js mounts it
        # into #dash-root, resolves its bare file names to assets/ and runs its scripts in order (decision 0011).
        config["page"] = "artifact"
        config["assets"] = sorted(d.assets)
        page = f'<template id="dash-artifact">{page}</template>'
    usage.record("view", ENV, user.email, d.slug)
    return shell(user, title=d.title, active=d.slug, config=config, page=page, libs=d.libs, artifact=d.page_kind == "artifact")


@app.get("/d/{slug}/assets/{name}")
def dashboard_asset(request: Request, slug: str, name: str):
    """A file from a page: artifact dashboard's assets/ folder. Only names the registry accepted are served."""
    d, _ = board_for(request, slug)
    path = d.assets.get(name)
    if path is None:
        raise HTTPException(404, "File not found")
    # no-cache = revalidate each time (ETag), so a changed file shows at once; unchanged ones aren't sent again
    return FileResponse(path, media_type=ASSET_TYPES[path.suffix.lower()], headers={"Cache-Control": "private, no-cache"})


@app.get("/api/d/{slug}/data/{dataset_id}")
async def dataset(request: Request, slug: str, dataset_id: str, refresh: int = 0):
    d, user = board_for(request, slug)
    ds = d.datasets.get(dataset_id)
    if not ds:
        raise HTTPException(404, "Unknown dataset")
    if not can_open(user, ds.groups):
        return JSONResponse({"error": "You don't have access to this part of the dashboard"}, status_code=403)
    if ds.todo:
        if not (PREVIEW_SNAPSHOTS and ds.snapshot):
            return JSONResponse({"error": "This data isn't connected to Databricks yet (todo in dashboard.yml)"}, status_code=409,
                                headers={"Cache-Control": "no-store"})
        try:
            payload = await asyncio.to_thread(snapshots.load, d, ds)
        except (OSError, ValueError) as e:
            return JSONResponse({"error": f"Snapshot preview: {e}"}, status_code=502, headers={"Cache-Control": "no-store"})
        now = time.time()
        return JSONResponse({**payload, "fetched_at": now, "expires_at": None, "cached": False, "cache": "snapshot",
                             "snapshot": True}, headers={"Cache-Control": "private, no-store"})
    raw = {k: v for k, v in request.query_params.items() if k in ds.params}
    if ds.auth == "app":
        client, who, raw = app_client(), "app", {}
    else:
        client, who = user.client, "shared" if ds.shared else user.key
    try:
        await asyncio.to_thread(access.SHARED_ACCESS.check, d, ds, client, user.key, raw)
        payload = await asyncio.to_thread(data.fetch, d, ds, client, who, raw, bool(refresh))
    except access.AccessDenied as e:
        return JSONResponse({"error": str(e)}, status_code=403, headers={"Cache-Control": "private, no-store"})
    except access.AccessUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=502, headers={"Cache-Control": "private, no-store"})
    except data.QueryError as e:
        log.warning("%s/%s failed: %s", slug, dataset_id, e)
        return JSONResponse({"error": str(e)}, status_code=502)
    headers = {"Cache-Control": "private, no-store", "ETag": f'"{payload["fetched_at"]}"'}
    if not refresh and payload["cached"] and request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return JSONResponse({**payload, "cache": ds.cache_kind, "data_through": data.data_through(ds, payload)}, headers=headers)


@app.get("/api/d/{slug}/sources")
async def dataset_sources(request: Request, slug: str, check: list[str] | None = Query(None)):
    """Read source metadata as the app. An explicit refresh check bypasses the display metadata cache."""
    d, user = board_for(request, slug)
    allowed = {k: v for k, v in d.datasets.items() if can_open(user, v.groups) and not v.todo}
    if check is None:
        body = {"datasets": await sources.for_datasets(allowed, app_client())}
    else:
        requested = {k: allowed[k] for k in set(check) & allowed.keys()}
        body = {"checks": await sources.refresh_checks(d, requested, app_client())}
    return JSONResponse(body, headers={"Cache-Control": "private, no-store"})


# ---------- Ask Genie (docs/DESIGN.md): always as the viewer, never as the app's service principal ----------

def genie_client(user: User) -> WorkspaceClient:
    return genie.client_for(user.client)


def genie_board(request: Request, slug: str) -> tuple[Dashboard, User, str]:
    d, user = board_for(request, slug)
    space = d.genie_space(ENV)
    if not space:
        raise HTTPException(404, "Genie isn't set up for this dashboard")
    return d, user, space


def genie_ids(*ids: str) -> None:
    if not all(isinstance(i, str) and genie.ID_RE.match(i) for i in ids):
        raise HTTPException(400, "That conversation or message id isn't valid")


async def genie_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > 32_000:
        raise HTTPException(413, "That request is too large")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "The request must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "The request must be a JSON object")
    return body


def genie_error(p: genie.GenieProblem, slug: str, what: str) -> JSONResponse:
    log.warning("genie %s on %s failed: %s", what, slug, p.status)  # never the question or Genie's text
    return JSONResponse({"error": p.message}, status_code=p.status, headers={"Cache-Control": "no-store"})


@app.post("/api/d/{slug}/genie/ask")
async def genie_ask(request: Request, slug: str):
    d, user, space = genie_board(request, slug)
    body = await genie_body(request)
    question = genie.clean_question(body.get("question"))
    if not question:
        raise HTTPException(400, "Type a question first")
    if len(question) > genie.MAX_QUESTION:
        raise HTTPException(400, f"Keep the question under {genie.MAX_QUESTION} characters")
    conv = body.get("conversation_id") or None
    if conv is not None:
        genie_ids(conv)
    block = genie.context_block(d, genie.clean_params(d, body.get("params")), genie.clean_context(body.get("context")))
    send_context = conv is None or genie.SENT.changed(user.key, conv, block)
    content = genie.message_text(block if send_context else None, question)
    try:
        ids = await asyncio.to_thread(genie.ask, genie_client(user), space, conv, content)
    except genie.GenieProblem as p:
        return genie_error(p, slug, "ask")
    genie.SENT.remember(user.key, ids["conversation_id"], block)
    usage.record("genie_ask", ENV, user.email, d.slug)
    return JSONResponse({**ids, "context_sent": send_context}, headers={"Cache-Control": "no-store"})


@app.get("/api/d/{slug}/genie/{conversation_id}/{message_id}")
async def genie_message(request: Request, slug: str, conversation_id: str, message_id: str):
    _, user, space = genie_board(request, slug)
    genie_ids(conversation_id, message_id)
    try:
        payload = await asyncio.to_thread(genie.poll, genie_client(user), space, conversation_id, message_id)
    except genie.GenieProblem as p:
        return genie_error(p, slug, "poll")
    return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})


@app.post("/api/d/{slug}/genie/{conversation_id}/{message_id}/feedback")
async def genie_feedback(request: Request, slug: str, conversation_id: str, message_id: str):
    d, user, space = genie_board(request, slug)
    genie_ids(conversation_id, message_id)
    rating = (await genie_body(request)).get("rating")
    if rating not in ("up", "down"):
        raise HTTPException(400, "rating must be up or down")
    try:
        await asyncio.to_thread(genie.feedback, genie_client(user), space, conversation_id, message_id, rating)
    except genie.GenieProblem as p:
        return genie_error(p, slug, "feedback")
    usage.record("genie_feedback", ENV, user.email, d.slug)
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


@app.post("/api/xlsx")
async def export_xlsx(request: Request):
    """Turns rows the page already holds into an Excel file (kit.xlsx). Nothing is read from Databricks here."""
    current_user(request)  # signed-in users only
    raw = await request.body()
    if len(raw) > 8_000_000:
        raise HTTPException(413, "Too much data for one Excel file")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("The request must be a JSON object")
        content = await asyncio.to_thread(xlsx.build, body.get("sheets"))
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as e:
        raise HTTPException(400, str(e)[:200] or "The Excel data was not valid")
    name = xlsx.safe_filename(body.get("name"))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@app.get("/api/health")
@app.get("/healthz")  # alias for local runs; the Databricks Apps proxy answers /healthz itself when deployed
def healthz():
    return {"ok": True, "env": ENV, "dashboards": len(LIVE), "broken": [k for k, v in DASHBOARDS.items() if v.errors],
            "hidden": [k for k, v in DASHBOARDS.items() if not v.errors and ENV not in v.environments]}
