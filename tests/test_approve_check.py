"""scripts/approve.py and scripts/check.py as run from the command line, against dashboards in tmp_path."""
import hashlib
import sys

import pytest
import yaml

from portal import registry
from scripts import approve, check

SQL = {"x": "SELECT 1 AS n FROM samples.tpch.region"}
MANIFEST = "title: S\nsection: Samples\ndatasets:\n  x: {sql: sql/x.sql, cache: shared}\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(module, monkeypatch, *args) -> int:
    monkeypatch.setattr(sys, "argv", [module.__name__, *args])
    return module.main()


@pytest.fixture()
def repo(tmp_path, monkeypatch, make_dashboard):
    """An empty dashboards folder and approval files in tmp_path, standing in for the real ones."""
    root = tmp_path / "dashboards"
    root.mkdir()
    pages, shared = tmp_path / "reviewed_pages.yml", tmp_path / "shared_cache.yml"
    monkeypatch.setattr(registry, "DASHBOARDS_DIR", root)
    monkeypatch.setattr(registry, "REVIEWED_PAGES", pages)
    monkeypatch.setattr(registry, "SHARED_APPROVALS", shared)
    monkeypatch.setattr(approve, "DASHBOARDS_DIR", root)
    monkeypatch.setattr(approve, "REVIEWED_PAGES", pages)
    monkeypatch.setattr(approve, "SHARED_APPROVALS", shared)
    monkeypatch.setattr(approve, "HEADERS", {pages: "# pages\n", shared: "# shared\n"})
    monkeypatch.setattr(check, "load_all", lambda env: registry.load_all(root, env))
    page = "<main><script>dash.data('x')</script></main>\n"
    return root, pages, shared, page


def make(repo, make_dashboard, slug="s", page=None):
    root, _, _, default = repo
    folder = make_dashboard(slug, MANIFEST, SQL, page or default)
    folder.rename(root / slug)
    return root / slug


def test_approve_unknown_slug_writes_nothing(repo, monkeypatch, capsys):
    _, pages, shared, _ = repo
    assert run(approve, monkeypatch, "nope", "--write") == 1
    assert "no dashboard at src/dashboards/nope" in capsys.readouterr().out
    assert not pages.exists() and not shared.exists()


def test_approve_without_write_prints_digests_only(repo, make_dashboard, monkeypatch, capsys):
    _, pages, shared, page = repo
    make(repo, make_dashboard)
    pages.write_text("old: 1\n", encoding="utf-8")
    assert run(approve, monkeypatch, "s") == 0
    out = capsys.readouterr().out
    assert f"s: {sha(page)}" in out and f"s/x: {sha(SQL['x'])}" in out
    assert pages.read_text(encoding="utf-8") == "old: 1\n" and not shared.exists()


def test_approve_write_replaces_only_that_slug(repo, make_dashboard, monkeypatch, capsys):
    _, pages, shared, page = repo
    make(repo, make_dashboard)
    pages.write_text("other: aaa\ns: stale\ns/assets/gone.js: stale\n", encoding="utf-8")
    shared.write_text("other/x: bbb\ns/gone: stale\n", encoding="utf-8")
    assert run(approve, monkeypatch, "s", "--write") == 0
    assert "updated src/reviewed_pages.yml: 1 entries for s" in capsys.readouterr().out
    assert yaml.safe_load(pages.read_text(encoding="utf-8")) == {"other": "aaa", "s": sha(page)}
    assert yaml.safe_load(shared.read_text(encoding="utf-8")) == {"other/x": "bbb", "s/x": sha(SQL["x"])}


def test_check_reviewed_dashboard_is_ok(repo, make_dashboard, monkeypatch, capsys):
    make(repo, make_dashboard)
    run(approve, monkeypatch, "s", "--write")
    capsys.readouterr()
    assert run(check, monkeypatch, "--static") == 0
    assert "ok   s: 1 datasets" in capsys.readouterr().out


def test_check_unreviewed_dashboard_fails(repo, make_dashboard, monkeypatch, capsys):
    make(repo, make_dashboard)
    assert run(check, monkeypatch, "--static") == 1
    assert "FAIL s: index.html has no matching review" in capsys.readouterr().out


def test_check_edited_page_fails_until_reviewed_again(repo, make_dashboard, monkeypatch, capsys):
    folder = make(repo, make_dashboard)
    run(approve, monkeypatch, "s", "--write")
    (folder / "index.html").write_text("<p>changed</p>", encoding="utf-8")
    capsys.readouterr()
    assert run(check, monkeypatch, "--static") == 1
    assert "FAIL s:" in capsys.readouterr().out
    run(approve, monkeypatch, "s", "--write")
    assert run(check, monkeypatch, "--static") == 0


def test_check_missing_sql_file_fails(repo, make_dashboard, monkeypatch, capsys):
    folder = make(repo, make_dashboard)
    run(approve, monkeypatch, "s", "--write")
    (folder / "sql" / "x.sql").unlink()
    capsys.readouterr()
    assert run(check, monkeypatch, "--static") == 1
    assert "FAIL s:" in capsys.readouterr().out
