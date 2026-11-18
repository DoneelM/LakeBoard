"""scripts/import_artifact.py and scripts/compare_snapshot.py on a synthetic artifact bundle (no Databricks)."""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import compare_snapshot as cs  # noqa: E402
import import_artifact as ia  # noqa: E402

BUNDLE = ROOT / "tests" / "fixtures" / "artifact_bundle"
BLOBS = BUNDLE / "_blobs"
TODAY = dt.date(2026, 11, 18)


def files_under(p: Path) -> set[str]:
    return {str(f.relative_to(p)).replace("\\", "/") for f in p.rglob("*") if f.is_file()}


@pytest.fixture()
def imported(tmp_path):
    root = tmp_path / "dashboards"
    root.mkdir()
    folder, lines = ia.import_bundle(BUNDLE, "bakehouse", BLOBS, root=root, today=TODAY)
    return folder, lines, yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8"))


@pytest.fixture()
def bundle_copy(tmp_path):
    """A copy of the fixture bundle to change in a test."""
    b = tmp_path / "bundle"
    shutil.copytree(BUNDLE, b)
    return b


def test_writes_the_dashboard_folder(imported):
    folder, _, _ = imported
    assert files_under(folder) == {
        "dashboard.yml", "index.html", "IMPORT.md", "assets/charts.js", "sql/sales.sql", "sql/reviews.sql",
        "sql/targets.sql", "snapshots/reviews.json", "snapshots/_import.json",
    }
    page = json.loads((BUNDLE / "files" / "index.html.json").read_text(encoding="utf-8"))["text"]
    assert (folder / "index.html").read_text(encoding="utf-8") == page  # unchanged, src="charts.js" kept
    assert 'src="charts.js"' in page


def test_manifest_is_a_draft_artifact_page(imported):
    _, _, m = imported
    assert m["title"] == "Bakehouse sales by country"
    assert (m["page"], m["status"], m["section"], m["groups"]) == ("artifact", "draft", "Drafts", [])
    assert m["owner"] == "TODO"
    assert "Bakehouse sales by country" in m["imported_from"] and "http" not in m["imported_from"]
    assert set(m["datasets"]) == {"sales", "reviews", "targets"}


def test_params_types_from_defaults_and_rules(imported):
    _, _, m = imported
    assert m["params"]["country"] == {"type": "STRING", "default": "USA"}
    assert m["params"]["start_date"] == {"type": "DATE", "default": "2024-05-01"}


@pytest.mark.parametrize("default, rule, expected", [
    (None, {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}, "DATE"),
    (None, {"type": "integer"}, "INT"),
    (None, {"type": "number"}, "DOUBLE"),
    (3, None, "INT"),
    (2.5, None, "DOUBLE"),
    (True, None, "BOOLEAN"),
    ("2024-01-31", None, "DATE"),
    ("North", {"type": "string", "enum": ["North"]}, "STRING"),
    (None, None, "STRING"),
])
def test_infer_type(default, rule, expected):
    assert ia.infer_type(default, rule)[0] == expected


def test_null_default_means_no_default(bundle_copy, tmp_path):
    (bundle_copy / "dash" / "params.json").write_text('{"country": null, "start_date": "2024-05-01"}', encoding="utf-8")
    folder, _ = ia.import_bundle(bundle_copy, "nulls", root=tmp_path, today=TODAY)
    m = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8"))
    assert m["params"]["country"] == {"type": "STRING"}


def test_databricks_call_becomes_parameterised_sql(imported):
    folder, _, m = imported
    sql = (folder / "sql" / "sales.sql").read_text(encoding="utf-8")
    assert "f.country = :country" in sql and "t.dateTime >= :start_date" in sql
    assert "{{" not in sql
    assert not sql.rstrip().endswith(";")
    assert "not enforced: enum" in sql  # the rule LakeBoard's typed params don't check
    assert ia.sql_problems(sql) == []
    assert "todo" not in m["datasets"]["sales"]


def test_blank_inside_a_longer_literal_becomes_concat():
    sql, names, notes, bare = ia.to_lakeboard_sql("SELECT * FROM samples.x.y WHERE n LIKE '%{{q}}%' AND k = {{k}};")
    assert "concat('%', :q, '%')" in sql and "k = :k" in sql and names == ["k", "q"]
    assert notes and bare == ["k"]


def test_sql_that_breaks_the_rules_is_reported_not_passed(bundle_copy, tmp_path):
    p = bundle_copy / "datasets" / "sales.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["source"]["args"]["query"] = "SELECT * FROM other_catalog.sales.orders WHERE c = '{{country}}'"
    p.write_text(json.dumps(doc), encoding="utf-8")
    folder, lines = ia.import_bundle(bundle_copy, "bad-sql", root=tmp_path, today=TODAY)
    m = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8"))
    assert m["datasets"]["sales"]["todo"] is True
    stub = (folder / "sql" / "sales.sql").read_text(encoding="utf-8")
    assert "IMPORT CHECK FAILED" in stub and "other_catalog" in stub
    assert all(ln.startswith("--") for ln in stub.splitlines())  # kept as comments, so the draft still loads
    assert any("sales: converted, but fails" in ln for ln in lines)
    assert "other_catalog" in (folder / "IMPORT.md").read_text(encoding="utf-8")


def test_file_dataset_is_todo_with_stub_and_snapshot(bundle_copy, tmp_path):
    (bundle_copy / "dash" / "refresh.json").unlink()  # no refresh routine: nothing to recover
    folder, _ = ia.import_bundle(bundle_copy, "stub", BLOBS, root=tmp_path / "d", today=TODAY)
    m = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8"))
    assert m["datasets"]["reviews"]["todo"] is True
    assert m["datasets"]["reviews"]["snapshot"] == "snapshots/reviews.json"
    stub = (folder / "sql" / "reviews.sql").read_text(encoding="utf-8")
    assert all(ln.startswith("--") for ln in stub.splitlines())
    # "reads samples.bakehouse.media_customer_reviews and sales_franchises": the bare name takes its catalog.schema
    assert "samples.bakehouse.media_customer_reviews, samples.bakehouse.sales_franchises" in stub
    assert "franchise_id, franchise, country, reviews" in stub
    assert "-- TODO" in stub


def test_sql_recovered_from_refresh_routine_stays_todo(imported):
    folder, lines, m = imported
    assert m["datasets"]["reviews"]["todo"] is True  # not live until it reconciles
    assert m["datasets"]["reviews"]["snapshot"] == "snapshots/reviews.json"
    sql = (folder / "sql" / "reviews.sql").read_text(encoding="utf-8")
    assert "Recovered from the artifact's dash/refresh refresh routine" in sql and "compare_snapshot" in sql
    body = [ln for ln in sql.splitlines() if not ln.startswith("--")]
    assert body[0].startswith("WITH r AS (") and body[-1] == "ORDER BY r.reviews DESC"
    assert "Run this SQL" not in sql and "Then save" not in sql  # the instructions are not carried over
    assert ia.sql_problems(sql) == []
    assert any("reviews: SQL recovered from refresh routine (reconcile)" in ln for ln in lines)
    assert "SQL recovered from refresh routine (reconcile)" in (folder / "IMPORT.md").read_text(encoding="utf-8")


def test_recovered_sql_that_breaks_the_rules_is_kept_as_comments(bundle_copy, tmp_path):
    p = bundle_copy / "dash" / "refresh.json"
    p.write_text(json.dumps({"reviews": "Run exactly:\nSELECT * FROM finance_prod.gold.reviews_vw;",
                             "nope": "SELECT 1 FROM samples.x.y"}), encoding="utf-8")
    folder, lines = ia.import_bundle(bundle_copy, "rec-bad", BLOBS, root=tmp_path / "d", today=TODAY)
    sql = (folder / "sql" / "reviews.sql").read_text(encoding="utf-8")
    assert all(ln.startswith("--") for ln in sql.splitlines())
    assert "IMPORT CHECK FAILED" in sql and "finance_prod" in sql
    assert any("fails LakeBoard's SQL rules" in ln for ln in lines)
    assert any("'nope', which is not a dataset" in ln for ln in lines)
    from portal.registry import load_dashboard
    assert load_dashboard(folder, env="prod").errors == []  # the draft still loads


@pytest.mark.parametrize("text, expected", [
    ("Run this SQL exactly as written:\nSELECT a FROM samples.x.y;\nReturn all rows.", "SELECT a FROM samples.x.y"),
    ("With the warehouse below, run:\nWITH t AS (SELECT 1 AS a)\nSELECT a FROM t\n\nReturn every row.",
     "WITH t AS (SELECT 1 AS a)\nSELECT a FROM t"),
    ("select x from samples.a.b where y = 'a;b'", "select x from samples.a.b where y = 'a;b'"),
    ("No query here.", None),
])
def test_extract_sql(text, expected):
    assert ia.extract_sql(text) == expected


def test_tables_named_resolves_bare_names():
    text = "Reads cat.schema.a_vw, b_vw, c_vw and cat2.schema.d_vw and joins them."
    assert ia.tables_named(text) == ["cat.schema.a_vw", "cat.schema.b_vw", "cat.schema.c_vw", "cat2.schema.d_vw"]
    assert ia.tables_named("Saved as reviews.csv by main.ops.jobs_log") == ["main.ops.jobs_log"]


def test_tokens_set_inline_or_from_script_are_not_unknown():
    page = ('<div style="--tc: red; color: var(--tc)"></div><style>.x { color: var(--rx-lc); width: var(--nope) }</style>'
            "<script>el.style.setProperty('--rx-lc', '#000'); Object.assign(el.style, {'--tk-dur': '1s'});"
            "el.animate([], {duration: 'var(--tk-dur)'})</script>")
    assert ia.scan_page(page, {})["unknown_tokens"] == ["--nope"]


def test_snapshot_conversion(imported):
    folder, _, _ = imported
    snap = json.loads((folder / "snapshots" / "reviews.json").read_text(encoding="utf-8"))
    assert snap["columns"] == ["franchise_id", "franchise", "country", "reviews"]
    assert snap["rows"][0] == ["3000005", "Sweet Crumbs", "USA", "12"]
    assert snap["rows"][3] == ["3000014", "Morning Loaf", "Australia", ""]
    assert len(snap["rows"]) == 4
    info = json.loads((folder / "snapshots" / "_import.json").read_text(encoding="utf-8"))
    assert info["reviews"]["saved"].startswith("2026-11-17")


def test_csv_splits_on_commas_only_and_json_rows(tmp_path):
    assert ia.read_delimited('a,b\n"x,y",2\n', ",") == (["a", "b"], [['"x', 'y"']])
    p = tmp_path / "d.json"
    p.write_text('[{"a": 1, "b": null}, {"a": 2.5, "c": true}]', encoding="utf-8")
    assert ia.snapshot_from(p, "json", "d.json") == (["a", "b", "c"], [["1", None, None], ["2.5", None, "true"]])


def test_missing_blob_is_reported(tmp_path):
    folder, _ = ia.import_bundle(BUNDLE, "no-blobs", None, root=tmp_path, today=TODAY)
    assert not (folder / "snapshots").exists()
    text = (folder / "IMPORT.md").read_text(encoding="utf-8")
    assert "0123456789abcdef0123456789abcdef" in text and "--blobs" in text


def test_other_connector_is_todo(imported):
    folder, _, m = imported
    assert m["datasets"]["targets"]["todo"] is True
    assert "snapshot" not in m["datasets"]["targets"]
    stub = (folder / "sql" / "targets.sql").read_text(encoding="utf-8")
    assert all(ln.startswith("--") for ln in stub.splitlines()) and "Lakehouse Federation" in stub
    assert "Lakehouse Federation" in (folder / "IMPORT.md").read_text(encoding="utf-8")


def test_page_scan(imported):
    folder, lines, _ = imported
    md = (folder / "IMPORT.md").read_text(encoding="utf-8")
    assert "`data-draw` elements: 3" in md
    assert "`dash-one-writer`" in md
    assert "`calc`" in md and "`draw`" in md
    assert "`charts.js`" in md
    assert "`--cds-text-tertiary`" in md  # used, not guaranteed
    assert "defines itself: `--bk-accent`" in md
    assert "(external URLs, fetch, iframes, forms): none" in md  # the SVG namespace is not a request


def test_page_scan_flags_unsupported():
    scan = ia.scan_page('<iframe src="https://example.com"></iframe><form></form><script>fetch("/x")</script>'
                        '<svg xmlns="http://www.w3.org/2000/svg"></svg><script>dash.loader("a")</script>', {})
    kinds = {u.split(" in ")[0] for u in scan["unsupported"]}
    assert kinds == {"external URL", "<iframe>", "<form>", "fetch()"}
    assert scan["loader"] == 1


def test_refuses_existing_folder_without_force(imported):
    folder, _, _ = imported
    with pytest.raises(FileExistsError):
        ia.import_bundle(BUNDLE, "bakehouse", BLOBS, root=folder.parent, today=TODAY)
    ia.import_bundle(BUNDLE, "bakehouse", BLOBS, force=True, root=folder.parent, today=TODAY)


def test_no_writes_outside_the_slug_folder(tmp_path):
    root = tmp_path / "dashboards"
    (root / "other").mkdir(parents=True)
    (root / "other" / "keep.txt").write_text("x", encoding="utf-8")
    before_bundle = files_under(BUNDLE)
    ia.import_bundle(BUNDLE, "bakehouse", BLOBS, root=root, today=TODAY)
    assert {p.name for p in tmp_path.iterdir()} == {"dashboards"}
    assert {p.name for p in root.iterdir()} == {"other", "bakehouse"}
    assert files_under(root / "other") == {"keep.txt"}
    assert files_under(BUNDLE) == before_bundle


def test_unsafe_or_unservable_files_are_skipped(bundle_copy, tmp_path):
    (bundle_copy / "files" / "..evil.js.json").write_text('{"text": "x"}', encoding="utf-8")
    (bundle_copy / "files" / "notes.md.json").write_text('{"text": "x"}', encoding="utf-8")
    folder, lines = ia.import_bundle(bundle_copy, "safe", root=tmp_path / "d", today=TODAY)
    assert files_under(folder / "assets") == {"charts.js"}
    assert sum("skipped" in ln for ln in lines) == 2


def test_the_portal_loads_the_import(imported):
    """The registry (runtime contract: page: artifact, status: draft, todo/snapshot, assets/) accepts the output."""
    from portal.registry import load_dashboard
    folder, _, _ = imported
    for env in ("dev", "prod"):
        board = load_dashboard(folder, env=env)
        assert board.errors == []
        assert board.datasets["reviews"].todo and board.datasets["reviews"].snapshot == "snapshots/reviews.json"
        assert board.datasets["targets"].todo and not board.datasets["sales"].todo
        assert board.page_kind == "artifact" and board.draft and set(board.assets) == {"charts.js"}
    assert "portal check" not in (folder / "IMPORT.md").read_text(encoding="utf-8")


def test_unreadable_input_exits_2(tmp_path, capsys):
    assert ia.main(["--bundle", str(tmp_path / "missing"), "--slug", "x", "--root", str(tmp_path)]) == 2
    bad = tmp_path / "bundle" / "dash"
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text("{not json", encoding="utf-8")
    assert ia.main(["--bundle", str(tmp_path / "bundle"), "--slug", "x", "--root", str(tmp_path)]) == 2
    assert not (tmp_path / "x").exists()


def test_bad_slug_refused(tmp_path):
    with pytest.raises(ia.BundleError):
        ia.import_bundle(BUNDLE, "../escape", root=tmp_path)


# ------------------------------------------------------------------ compare_snapshot

SNAP = {"columns": ["franchise", "country", "reviews"],
        "rows": [["Sweet Crumbs", "USA", "12"], ["Golden Crust", "Japan", "9"], ["Rye & Co", "Sweden", "7"]]}


def test_compare_reconciles_within_tolerance():
    live = {"columns": ["FRANCHISE", "country", "reviews"],
            "rows": [["Golden Crust", "Japan", "9.0"], ["Sweet Crumbs", "USA", "12.04"], ["Rye & Co", "Sweden", "7"]]}
    r = cs.compare(SNAP, live, tolerance=0.005)
    assert r["ok"] and r["keys"] == ["franchise", "country"] and r["matched"] == 3


def test_compare_reports_differences_and_one_sided_rows():
    live = {"columns": ["franchise", "country", "reviews", "extra"],
            "rows": [["Sweet Crumbs", "USA", "15", "1"], ["Golden Crust", "Japan", "9", "1"], ["New Bake", "USA", "1", "1"]]}
    r = cs.compare(SNAP, live, keys=["franchise"])
    assert not r["ok"]
    assert r["only_live_columns"] == ["extra"]
    assert r["only_snapshot"] == [{"franchise": "Rye & Co"}] and r["only_live"] == [{"franchise": "New Bake"}]
    assert r["differences"][0]["column"] == "reviews" and r["differences"][0]["snapshot"] == "12"
    text = "\n".join(cs.report(r, "s", "reviews", "2026-11-17", 0.005))
    assert "MISMATCH" in text and "2026-11-17" in text and "moved on" in text


def test_compare_without_keys_matches_whole_rows():
    snap = {"columns": ["n"], "rows": [["1"], ["1"], ["2"]]}
    assert cs.compare(snap, {"columns": ["n"], "rows": [["2"], ["1.0"], ["1"]]})["ok"]
    assert not cs.compare(snap, {"columns": ["n"], "rows": [["2"], ["1"]]})["ok"]


def test_compare_loads_dataset_and_params(imported):
    folder, _, _ = imported
    with pytest.raises(SystemExit):  # a comment-only stub can't run
        cs.load("bakehouse", "targets", "dev", {}, root=folder.parent)
    (folder / "sql" / "reviews.sql").write_text(
        "SELECT f.name AS franchise, COUNT(*) AS reviews FROM samples.bakehouse.media_customer_reviews AS r\n"
        "JOIN samples.bakehouse.sales_franchises AS f ON f.franchiseID = r.franchiseID\n"
        "WHERE :country IS NULL OR f.country = :country GROUP BY f.name;\n", encoding="utf-8")
    sql, params, snap, saved = cs.load("bakehouse", "reviews", "dev", {"country": "Japan"}, root=folder.parent)
    assert params == [{"name": "country", "type": "STRING", "value": "Japan"}]
    assert snap["columns"][0] == "franchise_id" and saved.startswith("2026-11-17") and not sql.endswith(";")
    with pytest.raises(SystemExit):  # sales has no snapshot
        cs.load("bakehouse", "sales", "dev", {}, root=folder.parent)
