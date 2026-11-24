"""Publishing guards (decision 0018): reviewed page digests, reviewed shared SQL, explicit groups for auth: app."""
import hashlib

import pytest

from portal import auth, registry
from portal.registry import Approvals, digest, load_all, load_dashboard

SQL = {"x": "SELECT 1 AS n FROM samples.tpch.region"}
SHARED = "title: S\nsection: Samples\ndatasets:\n  x: {sql: sql/x.sql, cache: shared}\n"
PAGE = "<main><script>dash.data('x')</script></main>\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def approved(slug="s", page=PAGE, sql=SQL["x"], **extra) -> Approvals:
    return Approvals(pages={slug: sha(page), **extra}, shared={f"{slug}/x": sha(sql)})


def test_every_sample_dashboard_is_reviewed():
    boards = load_all(env="prod")
    assert boards and all(not b.errors for b in boards.values()), {b.slug: b.errors for b in boards.values() if b.errors}


def test_digest_ignores_crlf_line_endings(tmp_path):
    lf, crlf = tmp_path / "a.html", tmp_path / "b.html"
    lf.write_bytes(b"<p>x</p>\n<p>y</p>\n")
    crlf.write_bytes(b"<p>x</p>\r\n<p>y</p>\r\n")
    assert digest(lf) == digest(crlf) == sha("<p>x</p>\n<p>y</p>\n")


def test_unreviewed_or_changed_page_is_refused(make_dashboard):
    folder = make_dashboard("s", SHARED, SQL, PAGE)
    assert load_dashboard(folder, env="prod", approvals=approved()).errors == []
    errs = load_dashboard(folder, env="prod", approvals=Approvals(pages={}, shared=approved().shared)).errors
    assert errs == ["index.html has no matching review in src/reviewed_pages.yml (python scripts/approve.py s)"]
    (folder / "index.html").write_text(PAGE + "<p>changed</p>", encoding="utf-8")
    assert any("reviewed_pages.yml" in e for e in load_dashboard(folder, env="prod", approvals=approved()).errors)


def test_artifact_assets_need_their_own_review(make_dashboard):
    page = '<meta name="dash-one-writer"><script src="app.js"></script><script>dash.data("x")</script>'
    folder = make_dashboard("s", SHARED + "page: artifact\n", SQL, page)
    (folder / "assets").mkdir()
    (folder / "assets" / "app.js").write_text("dash.onData(() => {});", encoding="utf-8")
    errs = load_dashboard(folder, env="prod", approvals=approved(page=page)).errors
    assert errs == ["assets/app.js has no matching review in src/reviewed_pages.yml (python scripts/approve.py s)"]
    ok = approved(page=page, **{"s/assets/app.js": sha("dash.onData(() => {});")})
    assert load_dashboard(folder, env="prod", approvals=ok).errors == []


def test_shared_sql_needs_review_but_page_review_is_separate(make_dashboard):
    folder = make_dashboard("s", SHARED, SQL, PAGE)
    no_sql = Approvals(pages=approved().pages, shared={})
    errs = load_dashboard(folder, env="prod", approvals=no_sql).errors
    assert len(errs) == 1 and "cache: shared needs a review of its SQL" in errs[0]
    (folder / "sql" / "x.sql").write_text(SQL["x"] + " WHERE r_regionkey = 1", encoding="utf-8")
    assert any("shared_cache.yml" in e for e in load_dashboard(folder, env="prod", approvals=approved()).errors)


def test_per_viewer_and_todo_datasets_need_no_sql_review(make_dashboard):
    manifest = "title: S\nsection: Samples\ndatasets:\n  x: {sql: sql/x.sql}\n  t: {sql: sql/t.sql, cache: shared, todo: true}\n"
    page = "<script>dash.data('x'); dash.data('t')</script>"
    folder = make_dashboard("s", manifest, {**SQL, "t": "-- todo"}, page)
    assert load_dashboard(folder, env="prod", approvals=Approvals(pages={"s": sha(page)}, shared={})).errors == []


def test_folders_outside_src_dashboards_skip_the_gate_unless_asked(make_dashboard):
    assert load_dashboard(make_dashboard("s", SHARED, SQL, PAGE), env="prod").errors == []


def test_missing_or_malformed_approval_files_fail_closed(tmp_path, monkeypatch):
    pages, shared = tmp_path / "reviewed_pages.yml", tmp_path / "shared_cache.yml"
    monkeypatch.setattr(registry, "REVIEWED_PAGES", pages)
    monkeypatch.setattr(registry, "SHARED_APPROVALS", shared)
    assert registry.load_approvals() == Approvals(pages={}, shared={})  # missing: nothing is approved
    pages.write_text("- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed_pages.yml"):
        registry.load_approvals()


@pytest.mark.parametrize("board_groups, ds_groups, ok", [
    ("[]", "[]", False), ("[analysts]", "[]", False), ("[]", "[analysts]", False), ("[analysts]", "[analysts]", True)])
def test_auth_app_needs_explicit_groups(make_dashboard, board_groups, ds_groups, ok):
    manifest = f"title: A\nsection: Samples\ngroups: {board_groups}\ndatasets:\n  x: {{sql: sql/x.sql, auth: app, groups: {ds_groups}}}\n"
    errs = load_dashboard(make_dashboard("a", manifest, SQL), env="prod").errors
    assert (not any("auth: app needs explicit groups" in e for e in errs)) is ok


def test_identity_cache_keys_on_a_hash_of_the_whole_token(monkeypatch):
    seen = []

    class Me:
        id, user_name, groups = "id1", "u@example.com", []

    class Client:
        def __init__(self, **kw):
            seen.append(kw["token"])
            self.current_user = type("C", (), {"me": staticmethod(lambda: Me())})()

    monkeypatch.setattr(auth, "WorkspaceClient", Client)
    monkeypatch.setattr(auth, "_identities", {})
    request = type("R", (), {"headers": {"x-forwarded-access-token": "a" * 40 + "same-suffix-of-24-chars!"}})()
    auth.current_user(request)
    other = type("R", (), {"headers": {"x-forwarded-access-token": "b" * 40 + "same-suffix-of-24-chars!"}})()
    auth.current_user(other)
    assert len(seen) == 2  # two tokens with the same ending are two identities
    assert all(len(k) == 64 and "suffix" not in k for k in auth._identities)
    assert auth._IDENTITY_TTL <= 60


def test_a_local_run_previews_unreviewed_work_but_a_deployed_app_does_not(make_dashboard):
    import app as portal_app
    folder = make_dashboard("s", SHARED, SQL, PAGE)
    board = load_dashboard(folder, env="prod", approvals=Approvals(pages={}, shared={}))
    assert len(board.unreviewed) == 2 and set(board.unreviewed) <= set(board.errors)
    assert portal_app.blocking_errors(board, local=True) == []
    assert portal_app.blocking_errors(board, local=False) == board.errors
    board.errors.append("dataset x: SQL must start with SELECT or WITH")
    assert portal_app.blocking_errors(board, local=True) == ["dataset x: SQL must start with SELECT or WITH"]
