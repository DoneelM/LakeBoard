"""Claude Dashboard artifact pages in the portal (decision 0011): page: artifact, assets/, status: draft,
todo datasets and their local snapshot preview."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from portal import snapshots
from portal.auth import User, can_open_dashboard
from portal.registry import load_dashboard
from portal.settings import DRAFTS_GROUPS, SECTIONS, is_deployed, is_local_run

ONE = "title: A\nsection: Samples\ndatasets:\n  x: {sql: sql/x.sql}\n"
SQL = {"x": "SELECT 1 AS n FROM samples.tpch.region"}


def user(*groups):
    return User(key="u1", email="u1@example.com", groups=frozenset(groups), client=None)


def add_assets(folder, files):
    (folder / "assets").mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / "assets" / name).write_text(text, encoding="utf-8")


# ---------- page: artifact and assets/ ----------

def test_page_defaults_to_lakeboard_and_accepts_artifact(make_dashboard):
    assert load_dashboard(make_dashboard("plain", ONE, SQL), env="prod").page_kind == "lakeboard"
    d = load_dashboard(make_dashboard("art", ONE + "page: artifact\n", SQL), env="prod")
    assert d.errors == [] and d.page_kind == "artifact"


def test_unknown_page_kind_is_refused(make_dashboard):
    errs = " ".join(load_dashboard(make_dashboard("bad", ONE + "page: iframe\n", SQL), env="prod").errors)
    assert "page must be one of" in errs


def test_artifact_assets_are_listed_and_bare_names_must_exist(make_dashboard):
    page = '<meta name="dash-one-writer"><link rel="stylesheet" href="theme.css"><script src="app.js"></script>' \
           '<script src="./missing.js"></script><script>dash.data("x")</script>'
    folder = make_dashboard("art", ONE + "page: artifact\n", SQL, page)
    add_assets(folder, {"app.js": "dash.onData(() => dash.data('x'));", "theme.css": "body{}", "logo.svg": "<svg/>"})
    d = load_dashboard(folder, env="prod")
    assert sorted(d.assets) == ["app.js", "logo.svg", "theme.css"]
    assert d.errors == ["index.html loads 'missing.js', which is not in assets/"]


def test_assets_only_for_artifact_pages(make_dashboard):
    folder = make_dashboard("plain", ONE, SQL)
    add_assets(folder, {"app.js": ""})
    errs = " ".join(load_dashboard(folder, env="prod").errors)
    assert "only used by page: artifact" in errs


@pytest.mark.parametrize("name", ["data.json", "notes.html", "run.py", ".hidden.js", "a..js"])
def test_assets_refuse_other_types_and_odd_names(make_dashboard, name):
    folder = make_dashboard("art", ONE + "page: artifact\n", SQL)
    add_assets(folder, {name: "x"})
    d = load_dashboard(folder, env="prod")
    assert name not in d.assets and any(f"assets/{name}" in e for e in d.errors)


def test_assets_refuse_folders(make_dashboard):
    folder = make_dashboard("art", ONE + "page: artifact\n", SQL)
    (folder / "assets" / "sub").mkdir(parents=True)
    (folder / "assets" / "sub" / "x.js").write_text("", encoding="utf-8")
    d = load_dashboard(folder, env="prod")
    assert d.assets == {} and any("only plain files" in e for e in d.errors)


def test_asset_scripts_are_checked_for_datasets_and_calcs_count(make_dashboard):
    folder = make_dashboard("art", ONE + "page: artifact\n", SQL, '<script src="app.js"></script>')
    add_assets(folder, {"app.js": "dash.calc('mix', {inputs: ['x'], fn: (r) => r}); dash.data('mix'); dash.data('nope');"})
    errs = load_dashboard(folder, env="prod").errors
    assert errs == ["assets/app.js reads dataset 'nope', which dashboard.yml does not declare"]


def test_remote_script_in_an_asset_is_refused(make_dashboard):
    folder = make_dashboard("art", ONE + "page: artifact\n", SQL)
    add_assets(folder, {"app.js": "document.write('<script src=\"https://evil.example/x.js\"></script>')"})
    assert any("script from another site" in e for e in load_dashboard(folder, env="prod").errors)


# ---------- status: draft ----------

def test_status_draft_and_drafts_settings(make_dashboard):
    assert load_dashboard(make_dashboard("live", ONE, SQL), env="prod").draft is False
    d = load_dashboard(make_dashboard("dr", ONE.replace("Samples", "Drafts") + "status: draft\n", SQL), env="prod")
    assert d.errors == [] and d.draft
    assert "Drafts" in SECTIONS
    assert DRAFTS_GROUPS == ["lakeboard-admins"]
    errs = " ".join(load_dashboard(make_dashboard("bad", ONE + "status: hidden\n", SQL), env="prod").errors)
    assert "status must be one of" in errs


def test_draft_visibility(make_dashboard):
    draft = load_dashboard(make_dashboard("dr", ONE + "status: draft\n", SQL), env="prod")
    live = load_dashboard(make_dashboard("lv", ONE, SQL), env="prod")
    owned = load_dashboard(make_dashboard("ow", ONE + "status: draft\ngroups: [finance]\n", SQL), env="prod")
    admins = ["lakeboard-admins"]
    assert can_open_dashboard(user(), live, admins)  # groups: [] = everyone
    assert not can_open_dashboard(user(), draft, admins)  # ...but never for a draft
    assert can_open_dashboard(user("lakeboard-admins"), draft, admins)
    assert can_open_dashboard(user("finance"), owned, admins) and can_open_dashboard(user("lakeboard-admins"), owned, admins)
    assert not can_open_dashboard(user("sales"), owned, admins)
    assert not can_open_dashboard(user("lakeboard-admins"), draft, [])  # an empty drafts_groups means nobody
    assert can_open_dashboard(user(), draft, admins, local=True)  # a local run shows the developer their drafts
    assert not can_open_dashboard(user("sales"), owned, admins, local=True)  # but still applies the dashboard's groups


# ---------- todo datasets and snapshots ----------

TODO = "title: A\nsection: Samples\npage: artifact\ndatasets:\n  x: {sql: sql/x.sql, todo: true, snapshot: snapshots/x.json}\n"


def test_todo_dataset_accepts_a_comment_only_stub_and_warns(make_dashboard):
    folder = make_dashboard("td", TODO,
                            {"x": "-- TODO: write the query for x\n/* columns: a, b */\n"})
    d = load_dashboard(folder, env="prod")
    assert d.errors == []
    ds = d.datasets["x"]
    assert ds.todo and ds.snapshot == "snapshots/x.json" and ds.cache_kind == "todo"
    assert any("x is todo" in w for w in d.warnings)


def test_stub_sql_is_refused_without_todo(make_dashboard):
    errs = " ".join(load_dashboard(make_dashboard("st", ONE, {"x": "-- nothing yet"}), env="prod").errors)
    assert "must start with SELECT or WITH" in errs


def test_todo_sql_that_is_written_is_still_checked(make_dashboard):
    manifest = ONE.replace("{sql: sql/x.sql}", "{sql: sql/x.sql, todo: true}")
    errs = " ".join(load_dashboard(make_dashboard("tw", manifest, {"x": "DELETE FROM samples.tpch.region"}), env="prod").errors)
    assert "DELETE" in errs


@pytest.mark.parametrize("spec, message", [
    ("{sql: sql/x.sql, snapshot: snapshots/x.json}", "only used with todo: true"),
    ("{sql: sql/x.sql, todo: true, snapshot: ../x.json}", "snapshot must be snapshots/<name>.json"),
    ("{sql: sql/x.sql, todo: true, snapshot: snapshots/../../x.json}", "snapshot must be snapshots/<name>.json"),
    ("{sql: sql/x.sql, todo: true, snapshot: snapshots/x.csv}", "snapshot must be snapshots/<name>.json"),
    ("{sql: sql/x.sql, todo: yes please}", "todo must be true or false"),
])
def test_bad_todo_and_snapshot_settings(make_dashboard, spec, message):
    errs = " ".join(load_dashboard(make_dashboard("bt", ONE.replace("{sql: sql/x.sql}", spec), SQL), env="prod").errors)
    assert message in errs


LOCAL = {"PORTAL_LOCAL_PROFILE": "dev", "PORTAL_PREVIEW_SNAPSHOTS": "1"}


def test_snapshot_preview_only_in_a_local_run():
    assert snapshots.preview_enabled(LOCAL)
    assert not snapshots.preview_enabled({"PORTAL_LOCAL_PROFILE": "dev"})  # not asked for
    assert not snapshots.preview_enabled({"PORTAL_PREVIEW_SNAPSHOTS": "1"})  # not a local run
    for deployed in ("DATABRICKS_APP_NAME", "DATABRICKS_APP_URL", "DATABRICKS_APP_PORT"):
        env = {**LOCAL, deployed: "lakeboard"}
        assert is_deployed(env) and not is_local_run(env) and not snapshots.preview_enabled(env)


@pytest.mark.parametrize("content", [
    {"columns": ["region", "n", "ok"], "rows": [["North", 1, True], ["South", 2.5, None]]},
    [{"region": "North", "n": 1, "ok": True}, {"region": "South", "n": 2.5, "ok": None}],
])
def test_snapshot_formats_load_as_strings(make_dashboard, content):
    folder = make_dashboard("sn", TODO, {"x": "-- todo"})
    (folder / "snapshots").mkdir()
    (folder / "snapshots" / "x.json").write_text(json.dumps(content), encoding="utf-8")
    d = load_dashboard(folder, env="prod")
    out = snapshots.load(d, d.datasets["x"])
    assert out == {"columns": ["region", "n", "ok"], "rows": [["North", "1", "true"], ["South", "2.5", None]], "cut": False}


def test_snapshot_rows_must_match_columns(make_dashboard):
    folder = make_dashboard("sn", TODO, {"x": "-- todo"})
    (folder / "snapshots").mkdir()
    (folder / "snapshots" / "x.json").write_text('{"columns": ["a", "b"], "rows": [[1]]}', encoding="utf-8")
    d = load_dashboard(folder, env="prod")
    with pytest.raises(ValueError):
        snapshots.load(d, d.datasets["x"])


def test_snapshots_are_gitignored():
    root = os.path.join(os.path.dirname(__file__), "..", ".gitignore")
    assert "src/dashboards/*/snapshots/" in open(root, encoding="utf-8").read().splitlines()


# ---------- the app: serving pages, assets and todo datasets ----------

@pytest.fixture()
def portal(make_dashboard, monkeypatch):
    """The FastAPI app with one artifact dashboard (a todo dataset with a snapshot) and one draft."""
    import app as portal_app
    page = '<meta name="dash-one-writer"><link rel="stylesheet" href="theme.css"><script src="app.js"></script>'
    folder = make_dashboard("art", TODO, {"x": "-- todo"}, page)
    add_assets(folder, {"app.js": "dash.onData(() => dash.data('x'));", "theme.css": "p { color: red }"})
    (folder / "snapshots").mkdir()
    (folder / "snapshots" / "x.json").write_text('[{"a": 1}]', encoding="utf-8")
    (folder / "secret.txt").write_text("not an asset", encoding="utf-8")
    draft = make_dashboard("dr", ONE + "status: draft\n", SQL)
    boards = {b.slug: b for b in (load_dashboard(folder, env="prod"), load_dashboard(draft, env="prod"))}
    assert all(not b.errors for b in boards.values())
    monkeypatch.setattr(portal_app, "LIVE", boards)
    monkeypatch.setattr(portal_app, "current_user", lambda request: user())
    monkeypatch.setattr(portal_app, "LOCAL_RUN", False)
    monkeypatch.setattr(portal_app, "PREVIEW_SNAPSHOTS", False)
    return portal_app, TestClient(portal_app.app)


def test_artifact_page_is_sent_inert_with_the_runtime(portal):
    _, client = portal
    r = client.get("/d/art")
    assert r.status_code == 200
    html = r.text
    assert '<template id="dash-artifact"><meta name="dash-one-writer">' in html
    assert '<script src="app.js"></script></template>' in html  # unchanged, inside the template
    assert "/static/artifact.js" in html and "/static/artifact.css" in html
    assert '"page": "artifact"' in html and '"assets": ["app.js", "theme.css"]' in html


def test_assets_are_served_and_nothing_else(portal):
    _, client = portal
    r = client.get("/d/art/assets/app.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/d/art/assets/theme.css").headers["content-type"].startswith("text/css")
    for bad in ("secret.txt", "..%2Fsecret.txt", "..%2F..%2Fdashboard.yml", "%2E%2E%2Fsecret.txt", "missing.js"):
        assert client.get(f"/d/art/assets/{bad}").status_code == 404, bad
    assert client.get("/d/art/assets/../secret.txt").status_code == 404
    assert client.get("/d/dr/assets/app.js").status_code == 403  # the draft: no access, so not even a 404


def test_draft_hidden_from_nav_and_refused(portal):
    portal_app, client = portal
    assert client.get("/d/dr").status_code == 403
    assert "/d/dr" not in client.get("/").text
    portal_app.current_user = lambda request: user("lakeboard-admins")
    home = client.get("/").text
    assert "/d/dr" in home and "pn-draft" in home
    assert client.get("/d/dr").status_code == 200


def test_todo_dataset_refused_unless_local_preview(portal, monkeypatch):
    portal_app, client = portal
    r = client.get("/api/d/art/data/x")
    assert r.status_code == 409 and "isn't connected" in r.json()["error"]
    monkeypatch.setattr(portal_app, "PREVIEW_SNAPSHOTS", True)
    body = client.get("/api/d/art/data/x").json()
    assert body["columns"] == ["a"] and body["rows"] == [["1"]] and body["snapshot"] is True and body["cache"] == "snapshot"


def test_deployed_app_never_turns_on_snapshot_preview(monkeypatch):
    for k, v in {**LOCAL, "DATABRICKS_APP_NAME": "lakeboard"}.items():
        monkeypatch.setenv(k, v)
    assert not snapshots.preview_enabled()


def test_artifact_tokens_are_defined():
    """Every design token an artifact may rely on has a LakeBoard definition."""
    static = os.path.join(os.path.dirname(__file__), "..", "src", "static")
    css = "".join(open(os.path.join(static, f), encoding="utf-8").read() for f in ("shell.css", "artifact.css"))
    tokens = ["--color-fg", "--color-fg-muted", "--color-bg", "--color-panel", "--color-border-line", "--color-ok",
              "--color-warn", "--color-bad", "--font-anthropic-sans", "--font-anthropic-serif", "--cds-font-weight-medium",
              "--cds-radius", "--cds-chart-muted", "--cds-chart-status-critical", "--cds-chart-grid", "--cds-chart-axis",
              "--cds-chart-reference", "--cds-surface-popover", "--cds-border", "--cds-shadow-popover",
              "--cds-text-secondary", "--cds-dur-slow", "--cds-ease-out", "--dash-gutter"]
    tokens += [f"--cds-font-size-{s}" for s in ("caption", "body", "heading", "title")]
    tokens += [f"--cds-{k}-{s}" for k in ("gap", "pad") for s in ("xs", "sm", "md", "lg", "xl")]
    assert [t for t in tokens if f"{t}:" not in css] == []
