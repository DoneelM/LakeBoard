"""The freshness label's server side: cache metadata on datasets, `source:` notes, and /sources (Unity Catalog
metadata, here from a fake WorkspaceClient)."""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from conftest import write_dashboard  # noqa: E402
from portal.registry import Dataset, load_dashboard  # noqa: E402


# --- `source:` and cache type ---

def write_source_board(tmp_path, source_line, name):
    d = tmp_path / name
    (d / "sql").mkdir(parents=True)
    (d / "dashboard.yml").write_text(f"title: S\ndatasets:\n  x:\n    sql: sql/x.sql\n{source_line}\n")
    (d / "sql" / "x.sql").write_text("SELECT * FROM samples.tpch.orders")
    (d / "index.html").write_text("<script>dash.data('x')</script>")
    return load_dashboard(d)


def test_source_note_is_validated(tmp_path):
    ok = write_source_board(tmp_path, '    source: "Built by the nightly orders job at 06:00"', "ok")
    assert ok.errors == [] and ok.datasets["x"].source == "Built by the nightly orders job at 06:00"
    assert write_source_board(tmp_path, "", "none").datasets["x"].source == ""
    exactly = write_source_board(tmp_path, "    source: " + "a" * 200, "max")
    assert exactly.errors == []
    too_long = write_source_board(tmp_path, "    source: " + "a" * 201, "long")
    assert any("at most 200 characters" in e for e in too_long.errors)
    for i, wrong in enumerate(["[1, 2]", "0", "{a: b}"]):
        board = write_source_board(tmp_path, f"    source: {wrong}", f"wrong{i}")
        assert any("source must be text" in e for e in board.errors), wrong


def test_cache_kind():
    assert Dataset(id="a", title="a", sql="", params=[], cache_ttl=1, auth="app", shared=True).cache_kind == "app"
    assert Dataset(id="a", title="a", sql="", params=[], cache_ttl=1, auth="user", shared=True, warm=[{"region": "North"}]).cache_kind == "warm"
    assert Dataset(id="a", title="a", sql="", params=[], cache_ttl=1, auth="user").cache_kind == "user"
    assert Dataset(id="a", title="a", sql="", params=[], cache_ttl=1, auth="user", shared=True).cache_kind == "shared"


# --- portal.sources with a fake Tables API ---

class FakeTables:
    """tables.get over a dict: name -> TableInfo, or an Exception to raise. Unknown names raise 'not found'."""

    def __init__(self, infos):
        self.infos, self.calls = infos, []

    def get(self, full_name, include_browse=None):
        self.calls.append(full_name)
        v = self.infos.get(full_name)
        if v is None:
            raise Exception(f"TABLE_OR_VIEW_NOT_FOUND {full_name}")
        if isinstance(v, Exception):
            raise v
        return v


def workspace(tables):
    return type("W", (), {"tables": tables})()


def view(*deps, updated=1):
    from databricks.sdk.service.catalog import (Dependency, DependencyList, FunctionDependency, TableDependency, TableInfo,
                                                TableType)
    ds = [Dependency(table=TableDependency(table_full_name=x)) for x in deps]
    ds.append(Dependency(function=FunctionDependency(function_full_name="core.f.ignored")))
    return TableInfo(table_type=TableType.VIEW, updated_at=updated, view_dependencies=DependencyList(dependencies=ds))


def table(ms):
    from databricks.sdk.service.catalog import DataSourceFormat, TableInfo, TableType
    return TableInfo(table_type=TableType.MANAGED, updated_at=ms, data_source_format=DataSourceFormat.DELTA)


def foreign(fmt="SNOWFLAKE_FORMAT"):
    from databricks.sdk.service.catalog import DataSourceFormat, TableInfo, TableType
    return TableInfo(table_type=TableType.FOREIGN, updated_at=9_000_000_000_000, data_source_format=DataSourceFormat(fmt))


def external():
    from databricks.sdk.service.catalog import TableInfo, TableType
    return TableInfo(table_type=TableType.EXTERNAL, updated_at=9_000_000_000_000)


def M(name, sec):
    """A managed table as /sources reports it."""
    return {"name": name, "kind": "managed", "updated_at": sec}


def U(name, kind="unknown", **extra):
    """A table with no time: unknown, live (with `via`) or external."""
    return {"name": name, "kind": kind, "updated_at": None, **extra}


@pytest.fixture()
def sources(monkeypatch):
    from portal import sources as mod
    monkeypatch.setattr(mod, "_cache", {})
    monkeypatch.setattr(mod, "_warned", set())
    monkeypatch.setattr(mod, "_map", {})  # no deploy-time map unless a test loads one
    return mod


def test_views_resolve_to_tables_and_the_newest_time_wins(sources):
    tables = FakeTables({
        "main_prod.ops.a_vw": view("main_prod.ops.mid_vw", "core.s.t1", updated=9_999_999_999_999),
        "main_prod.ops.mid_vw": view("staging.s.t2"),
        "core.s.t1": table(1_700_000_000_000),
        "staging.s.t2": table(1_700_000_500_000),
    })
    ds = Dataset(id="x", title="X", sql="SELECT * FROM main_prod.ops.a_vw -- JOIN main_prod.ops.commented",
                 params=[], cache_ttl=60, auth="app", source="note")
    out = asyncio.run(sources.for_datasets({"x": ds}, workspace(tables)))["x"]
    assert out["source_note"] == "note"
    assert out["tables"] == [M("core.s.t1", 1_700_000_000), M("staging.s.t2", 1_700_000_500)]
    assert out["source_updated_at"] == 1_700_000_500  # the newest table, never the view's own (DDL) time
    assert out["live"] is False and out["partial"] is False
    assert "main_prod.ops.commented" not in tables.calls
    asyncio.run(sources.for_datasets({"x": ds}, workspace(tables)))
    assert len(tables.calls) == 4  # the second request is served from the cache


def test_cycles_depth_missing_and_permission_errors(sources):
    from databricks.sdk.errors import PermissionDenied
    infos = {
        "c.s.loop_a": view("c.s.loop_b"), "c.s.loop_b": view("c.s.loop_a", "c.s.ok"), "c.s.ok": table(2_000_000_000_000),
        "c.s.denied_vw": view("c.s.secret"), "c.s.secret": PermissionDenied("User does not have USE SCHEMA"),
    }
    for i in range(10):  # a chain deeper than MAX_DEPTH
        infos[f"c.s.d{i}"] = view(f"c.s.d{i + 1}")
    infos["c.s.d10"] = table(1)
    fake = workspace(FakeTables(infos))
    assert sources.resolve(fake, "c.s.loop_a") == [M("c.s.ok", 2_000_000_000)]
    assert sources.resolve(fake, "c.s.denied_vw") == [U("c.s.secret")]
    assert sources.resolve(fake, "c.s.d0") == [U(f"c.s.d{sources.MAX_DEPTH}")]
    assert sources.resolve(fake, "c.s.missing") == [U("c.s.missing")]
    assert sources._warned == {"c.s.secret", "c.s.missing"}


def test_foreign_tables_are_live_and_external_tables_untracked(sources):
    # Neither is timed: their updated_at is a metadata-sync or registration time, not the last data write.
    fake = workspace(FakeTables({
        "c.s.fleet_vw": view("snowflake_fc.edc.trips", "fabric_fc.dbo.lines", "c.s.ext", "c.s.managed"),
        "snowflake_fc.edc.trips": foreign(),
        "fabric_fc.dbo.lines": foreign("DELTA"),  # a format that doesn't name the remote system
        "c.s.ext": external(),
        "c.s.managed": table(1_000_000),
    }))
    assert sources.resolve(fake, "c.s.fleet_vw") == [
        U("c.s.ext", "external"), M("c.s.managed", 1_000),
        U("fabric_fc.dbo.lines", "live", via=None), U("snowflake_fc.edc.trips", "live", via="Snowflake")]
    assert sources._warned == set()  # not a failure, so nothing is logged


def summary(sources, *tables):
    out = sources._summary("", list(tables))
    return out["source_updated_at"], out["live"], out["partial"]


def test_live_tables_dont_hide_the_managed_time(sources):
    # A dataset that reads a few federated tables beside managed ones.
    assert summary(sources, M("a", 5), M("b", 7), U("f", "live", via="Snowflake")) == (7, True, True)


def test_external_tables_dont_hide_the_managed_time(sources):
    assert summary(sources, M("a", 5), U("e", "external")) == (5, False, True)


def test_only_live_tables_have_no_time(sources):
    # Data read live is current when fetched, so "newer data available" can't be worked out: no time, no cue.
    assert summary(sources, U("f", "live", via="Snowflake"), U("g", "live", via=None)) == (None, True, False)
    assert summary(sources, U("e", "external")) == (None, False, True)


def test_live_and_external_tables_end_to_end(sources):
    fake = workspace(FakeTables({
        "c.s.points_vw": view("fabric_fc.dbo.lines", "c.s.addr", "c.s.erp"),
        "fabric_fc.dbo.lines": foreign("DELTA"), "c.s.addr": external(), "c.s.erp": table(1_800_000_000_000),
        "c.s.fleet_vw": view("snowflake_fc.edc.trips"), "snowflake_fc.edc.trips": foreign(),
    }))
    ds = {"points": Dataset(id="points", title="P", sql="SELECT * FROM c.s.points_vw", params=[], cache_ttl=60, auth="app"),
          "fleet": Dataset(id="fleet", title="F", sql="SELECT * FROM c.s.fleet_vw", params=[], cache_ttl=60, auth="app")}
    out = asyncio.run(sources.for_datasets(ds, workspace(fake.tables)))
    pts, flt = out["points"], out["fleet"]
    assert (pts["source_updated_at"], pts["live"], pts["partial"]) == (1_800_000_000, True, True)
    assert (flt["source_updated_at"], flt["live"], flt["partial"]) == (None, True, False)
    assert flt["tables"] == [U("snowflake_fc.edc.trips", "live", via="Snowflake")]


def N(name):
    """A view known to read no table, as /sources reports it."""
    return {"name": name, "kind": "none", "updated_at": None}


def test_a_view_the_map_says_reads_no_table_is_none(sources, tmp_path):
    # A calendar view (main_prod.operations.date_vw) generated from a sequence reads no table. Explicit env, no DATABRICKS_HOST.
    sources.load_map("prod", write_map(tmp_path / "m.json", "prod", {"main_prod.operations.date_vw": []}))
    tables = FakeTables(browse_only({"main_prod.operations.date_vw"}, {"main_prod.operations.date_vw": None}))
    assert sources.resolve(workspace(tables), "main_prod.operations.date_vw") == [N("main_prod.operations.date_vw")]
    assert tables.calls == []  # answered from the map
    ds = Dataset(id="w", title="W", sql="SELECT * FROM main_prod.operations.date_vw", params=[], cache_ttl=60, auth="app")
    out = asyncio.run(sources.for_datasets({"w": ds}, workspace(tables)))["w"]
    assert out["source_updated_at"] is None and out["no_source"] is True
    assert (out["live"], out["partial"]) == (False, False)


def test_browse_only_lookup_with_no_dependencies_stays_unknown(sources):
    # No map, BROWSE only: the view comes back without view_dependencies, which doesn't mean it reads nothing.
    fake = workspace(FakeTables(browse_only({"c.s.cal_vw"}, {"c.s.cal_vw": None})))
    assert sources.resolve(fake, "c.s.cal_vw") == [U("c.s.cal_vw")]
    ds = Dataset(id="w", title="W", sql="SELECT * FROM c.s.cal_vw", params=[], cache_ttl=60, auth="app")
    out = asyncio.run(sources.for_datasets({"w": ds}, fake))["w"]
    assert out["no_source"] is False and out["source_updated_at"] is None


def test_full_access_lookup_that_finds_no_table_dependency_is_none(sources):
    from databricks.sdk.service.catalog import (Dependency, DependencyList, FunctionDependency, TableInfo, TableType)
    fn_only = TableInfo(table_type=TableType.VIEW, updated_at=1, view_dependencies=DependencyList(
        dependencies=[Dependency(function=FunctionDependency(function_full_name="c.f.calendar"))]))
    empty = TableInfo(table_type=TableType.VIEW, updated_at=1, view_dependencies=DependencyList(dependencies=[]))
    fake = workspace(FakeTables({"c.s.fn_vw": fn_only, "c.s.empty_vw": empty}))
    assert sources.resolve(fake, "c.s.fn_vw") == [N("c.s.fn_vw")]
    assert sources.resolve(fake, "c.s.empty_vw") == [N("c.s.empty_vw")]


def test_none_tables_dont_block_and_all_none_means_no_source(sources):
    one = sources._summary("", [N("a"), M("b", 7)])
    assert (one["source_updated_at"], one["no_source"], one["live"], one["partial"]) == (7, False, False, False)
    assert sources._summary("", [N("a")])["no_source"] is True
    assert sources._summary("", [N("a"), N("b")])["source_updated_at"] is None
    # a none table doesn't hide an unknown one, nor make a live-only dataset "no source"
    assert sources._summary("", [N("a"), U("b")])["no_source"] is False
    assert sources._summary("", [N("a"), U("f", "live", via=None)])["no_source"] is False
    assert sources._summary("", [])["no_source"] is False


def test_map_with_no_dependencies_is_what_the_build_script_records(sources):
    from databricks.sdk.service.catalog import DependencyList, TableInfo, TableType
    cal = TableInfo(table_type=TableType.VIEW, updated_at=1, view_dependencies=DependencyList(dependencies=[]))
    doc, failed = build_script().build(workspace(FakeTables({"main_prod.operations.date_vw": cal})),
                                       {"main_prod.operations.date_vw"}, "prod")
    assert doc["views"] == {"main_prod.operations.date_vw": []} and failed == []


def S(name):
    """A table in a static catalog, as /sources reports it."""
    return {"name": name, "kind": "static", "updated_at": None}


def test_tables_in_a_static_catalog_are_static_and_never_looked_up(sources, monkeypatch):
    # `samples` reports updated_at as the moment you ask, so its time would always say "newer data available".
    monkeypatch.setattr(sources, "STATIC_CATALOGS", frozenset({"samples"}))
    tables = FakeTables({"c.s.mix_vw": view("samples.tpch.orders", "c.s.t"), "c.s.t": table(1_000_000)})
    seen: set[str] = set()
    assert sources.resolve(workspace(tables), "c.s.mix_vw", seen) == [M("c.s.t", 1_000), S("samples.tpch.orders")]
    assert sources.resolve(workspace(tables), "samples.tpch.lineitem") == [S("samples.tpch.lineitem")]
    assert "samples.tpch.orders" not in tables.calls and "samples.tpch.lineitem" not in tables.calls
    assert "samples.tpch.orders" not in seen  # no BROWSE grant is printed for it


def test_static_tables_block_nothing_and_all_static_means_static(sources):
    def full(*tables):
        return sources._summary("", list(tables))
    only = full(S("samples.tpch.orders"), S("samples.tpch.customer"))
    assert (only["source_updated_at"], only["static"], only["live"], only["partial"], only["no_source"]) == (
        None, True, False, False, False)
    with_none = full(S("samples.tpch.orders"), N("c.s.date_vw"))
    assert with_none["static"] is True and with_none["no_source"] is False
    mixed = full(S("samples.tpch.orders"), M("c.s.t", 7))
    assert (mixed["source_updated_at"], mixed["static"], mixed["partial"]) == (7, False, False)
    blocked = full(S("samples.tpch.orders"), U("c.s.u"))
    assert (blocked["source_updated_at"], blocked["static"]) == (None, False)  # unknown still hides the time
    assert full(M("c.s.t", 7))["static"] is False and full()["static"] is False


def test_static_catalogs_come_from_the_settings_with_their_environment_names():
    from portal import settings
    assert "samples" in settings.STATIC_CATALOGS  # the shipped environments.yml
    assert all(c == c.lower() for c in settings.STATIC_CATALOGS)


def test_build_script_leaves_static_tables_out_of_the_map(sources, monkeypatch):
    monkeypatch.setattr(sources, "STATIC_CATALOGS", frozenset({"samples"}))
    tables = FakeTables({"c.s.mix_vw": view("samples.tpch.orders", "c.s.t"), "c.s.t": table(1)})
    doc, failed = build_script().build(workspace(tables), {"c.s.mix_vw", "samples.tpch.nation"}, "prod")
    assert doc["views"] == {"c.s.mix_vw": ["samples.tpch.orders", "c.s.t"]}
    assert doc["types"] == {"c.s.t": "MANAGED"} and failed == []
    assert not any(c.startswith("samples.") for c in tables.calls)


def test_one_unknown_table_makes_the_newest_time_unknown(sources):
    # Otherwise the page could say "source unchanged" when the unknown table is the one that changed.
    assert summary(sources, M("a", 5), U("b")) == (None, False, False)
    assert summary(sources, M("a", 5), U("b"), U("f", "live", via=None), U("e", "external"))[0] is None
    assert summary(sources, M("a", 5), M("b", 7)) == (7, False, False)
    assert summary(sources) == (None, False, False)


def test_the_number_of_tables_is_capped(sources):
    infos = {"c.s.wide": view(*[f"c.s.t{i}" for i in range(100)])}
    infos.update({f"c.s.t{i}": table(1000) for i in range(100)})
    tables = FakeTables(infos)
    out = sources.resolve(workspace(tables), "c.s.wide")
    assert len(tables.calls) == sources.MAX_TABLES
    assert any(t["kind"] == "unknown" for t in out)


def test_slow_metadata_is_time_boxed(sources):
    gate = threading.Event()

    class Slow:
        def get(self, full_name, include_browse=None):
            gate.wait(1)
            return table(1000)

    ds = Dataset(id="x", title="X", sql="SELECT * FROM c.s.slow", params=[], cache_ttl=60, auth="app")
    try:
        out = asyncio.run(sources.for_datasets({"x": ds}, workspace(Slow()), timeout=0.2))["x"]
    finally:
        gate.set()
    assert out == {"source_note": "", "tables": [U("c.s.slow")], "source_updated_at": None, "live": False, "partial": False,
                   "no_source": False, "static": False}


# --- the deploy-time view map (scripts/build_sources_map.py) ---

def browse_only(view_names, infos):
    """What the app's service principal sees with BROWSE only: a view's type, but no view_dependencies."""
    from databricks.sdk.service.catalog import TableInfo, TableType
    return {k: (TableInfo(table_type=TableType.VIEW, updated_at=1) if k in view_names else v) for k, v in infos.items()}


NESTED = {
    "main_prod.operations.points_vw": view("main_prod.operations.address_vw", "core.erp.site"),
    "main_prod.operations.address_vw": view("core.erp.address", "core.archive.legacy_customer"),
    "core.erp.site": table(1_800_000_000_000),
    "core.erp.address": table(1_800_000_900_000),
    "core.archive.legacy_customer": table(1_700_000_000_000),
}
NESTED_VIEWS = {"main_prod.operations.points_vw", "main_prod.operations.address_vw"}


def write_map(path, env, views):
    import json
    path.write_text(json.dumps({"generated_at": "2026-11-17T00:00:00+00:00", "env": env, "views": views, "types": {}}))
    return path


def test_map_resolves_views_the_app_can_only_browse(sources, tmp_path):
    views = {"main_prod.operations.points_vw": ["main_prod.operations.address_vw", "core.erp.site"],
             "main_prod.operations.address_vw": ["core.erp.address", "core.archive.legacy_customer"]}
    assert sources.load_map("prod", write_map(tmp_path / "m.json", "prod", views)) == 2
    tables = FakeTables(browse_only(NESTED_VIEWS, NESTED))
    out = sources.resolve(workspace(tables), "main_prod.operations.points_vw")
    assert out == [M("core.archive.legacy_customer", 1_700_000_000), M("core.erp.address", 1_800_000_900),
                   M("core.erp.site", 1_800_000_000)]
    assert set(tables.calls) == {"core.erp.site", "core.erp.address", "core.archive.legacy_customer"}


def test_without_the_map_browse_only_views_are_unknown(sources, tmp_path):
    assert sources.load_map("prod", tmp_path / "missing.json") == 0
    fake = workspace(FakeTables(browse_only(NESTED_VIEWS, NESTED)))
    assert sources.resolve(fake, "main_prod.operations.points_vw") == [U("main_prod.operations.points_vw")]
    # with full metadata (no map needed) the views are followed through view_dependencies, as before
    sources._cache.clear()
    assert len(sources.resolve(workspace(FakeTables(NESTED)), "main_prod.operations.points_vw")) == 3


def test_a_map_for_another_environment_or_broken_is_ignored(sources, tmp_path):
    views = {"main_prod.operations.points_vw": ["core.erp.site"]}
    assert sources.load_map("dev", write_map(tmp_path / "m.json", "prod", views)) == 0
    assert sources._map == {}
    (tmp_path / "bad.json").write_text("{not json")
    assert sources.load_map("prod", tmp_path / "bad.json") == 0
    fake = workspace(FakeTables(browse_only(NESTED_VIEWS, NESTED)))
    assert sources.resolve(fake, "main_prod.operations.points_vw") == [U("main_prod.operations.points_vw")]


def test_a_view_missing_from_the_map_is_looked_up(sources, tmp_path):
    sources.load_map("prod", write_map(tmp_path / "m.json", "prod", {"c.s.other_vw": ["c.s.t"]}))
    assert len(sources.resolve(workspace(FakeTables(NESTED)), "main_prod.operations.points_vw")) == 3


def build_script():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_sources_map.py"
    spec = importlib.util.spec_from_file_location("build_sources_map", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_script_writes_views_and_types(sources):
    infos = dict(NESTED, **{"main_prod.operations.points_vw": view("main_prod.operations.address_vw",
                                                                      "core.erp.site", "fabric_fc.dbo.lines"),
                            "fabric_fc.dbo.lines": foreign("DELTA"), "core.x.ext": external(),
                            "main_prod.operations.denied_vw": denied()})
    tables = FakeTables(infos)
    refs = {"main_prod.operations.points_vw", "main_prod.operations.address_vw", "core.x.ext",
            "main_prod.operations.denied_vw"}
    doc, failed = build_script().build(workspace(tables), refs, "prod")
    assert doc["env"] == "prod" and doc["generated_at"].startswith("20")
    assert doc["views"] == {
        "main_prod.operations.address_vw": ["core.erp.address", "core.archive.legacy_customer"],
        "main_prod.operations.points_vw": ["main_prod.operations.address_vw", "core.erp.site", "fabric_fc.dbo.lines"]}
    assert doc["types"] == {"fabric_fc.dbo.lines": "FOREIGN", "core.archive.legacy_customer": "MANAGED",
                            "core.erp.address": "MANAGED", "core.erp.site": "MANAGED", "core.x.ext": "EXTERNAL"}
    assert failed == ["main_prod.operations.denied_vw"]
    assert len(tables.calls) == len(set(tables.calls))  # each name looked up once, however many datasets read it
    assert sources._cache == {}  # the app's cache isn't touched


def test_build_script_reads_only_dashboards_live_in_that_environment(tmp_path, monkeypatch):
    from portal import settings
    monkeypatch.setitem(settings.CATALOGS, "main_prod", {"dev": "main_dev", "test": "main_test"})
    everywhere = write_dashboard(tmp_path, "everywhere", "title: E\ndatasets:\n  x: {sql: sql/x.sql}\n",
                                 {"x": "SELECT * FROM main_prod.sales.orders"})
    dev_only = write_dashboard(tmp_path, "dev-only", "title: D\nenvironments: [dev]\ndatasets:\n  y: {sql: sql/y.sql}\n",
                               {"y": "SELECT * FROM samples.tpch.lineitem"})
    mod = build_script()
    monkeypatch.setattr(mod, "load_all", lambda env: {f.name: load_dashboard(f, env) for f in (everywhere, dev_only)})
    assert mod.references("prod") == {"main_prod.sales.orders"}
    assert mod.references("dev") == {"main_dev.sales.orders", "samples.tpch.lineitem"}


# --- the HTTP endpoints ---

DAILY_ORDERS = """title: Daily Orders
groups: [viewers]
datasets:
  orders:
    title: Daily orders
    sql: sql/orders.sql
    auth: app
    groups: [viewers]
    cache_ttl: 10m
    source: Refreshed by the orders job at 06:00, 10:00 and 14:00.
  exceptions:
    title: Order exceptions
    sql: sql/exceptions.sql
    auth: app
    groups: [viewers]
    cache_ttl: 10m
    source: Refreshed by the orders job at 06:00, 10:00 and 14:00.
"""


@pytest.fixture()
def api(monkeypatch, sources, tmp_path):
    """A signed-in viewer (not an analyst) on Daily Orders, with a group-restricted extra dataset."""
    from fastapi.testclient import TestClient
    import app as portal_app
    from portal import settings
    from portal.auth import User

    monkeypatch.setitem(settings.CATALOGS, "main_prod", {})  # an allowed catalog for this test only
    folder = write_dashboard(tmp_path, "daily-orders", DAILY_ORDERS, {
        "orders": "SELECT * FROM main_prod.operations.daily_orders_vw",
        "exceptions": "SELECT * FROM main_prod.operations.order_exceptions_vw"})
    board = load_dashboard(folder, env="prod")
    assert board.errors == []
    secret = Dataset(id="secret", title="Secret", sql="SELECT * FROM main_prod.ops.secret_vw", params=[], cache_ttl=60,
                     auth="app", groups=["analysts"])
    monkeypatch.setitem(board.datasets, "secret", secret)
    monkeypatch.setitem(portal_app.LIVE, board.slug, board)
    user = User(key="u2", email="viewer@example.com", groups=frozenset({"viewers"}), client=None)
    monkeypatch.setattr(portal_app, "current_user", lambda request: user)
    monkeypatch.setattr(portal_app.usage, "record", lambda *a: None)
    tables = FakeTables({
        "main_prod.operations.daily_orders_vw": view("core.orders.daily_orders"),
        "main_prod.operations.order_exceptions_vw": view("core.orders.order_exceptions"),
        "core.orders.daily_orders": table(1_794_000_000_000),
        "core.orders.order_exceptions": denied(),
        "main_prod.ops.secret_vw": table(1),
    })
    monkeypatch.setattr(portal_app, "app_client", lambda: workspace(tables))
    monkeypatch.setattr(portal_app.data, "run_sql", lambda client, sql, params, **kw:
                        {"columns": ["n"], "rows": [["1"]], "cut": False})
    monkeypatch.setattr(portal_app.data, "_cache", {})
    return TestClient(portal_app.app), tables


def denied():
    from databricks.sdk.errors import PermissionDenied
    return PermissionDenied("does not have BROWSE on catalog core")


def test_dataset_response_has_cache_type_and_expiry(api):
    client, _ = api
    body = client.get("/api/d/daily-orders/data/orders").json()
    assert body["cache"] == "app" and body["cached"] is False and body["rows"] == [["1"]]
    assert body["expires_at"] == pytest.approx(body["fetched_at"] + 600)
    assert body["query_started_at"] <= body["fetched_at"]
    again = client.get("/api/d/daily-orders/data/orders").json()
    assert again["cached"] is True and (again["fetched_at"], again["expires_at"]) == (body["fetched_at"], body["expires_at"])
    assert again["query_started_at"] == body["query_started_at"]


def test_conditional_dataset_response_only_omits_a_valid_cached_result(api, monkeypatch):
    from portal import data

    client, _ = api
    path = "/api/d/daily-orders/data/orders"
    first = client.get(path)
    headers = {"If-None-Match": first.headers["etag"]}
    tick = first.json()["fetched_at"]
    monkeypatch.setattr(data.time, "time", lambda: tick)  # a refresh in the same clock tick still needs a new ETag
    same = client.get(path, headers=headers)
    assert same.status_code == 304 and same.content == b""
    forced = client.get(path + "?refresh=1", headers=headers)
    assert forced.status_code == 200 and forced.json()["cached"] is False
    assert forced.json()["fetched_at"] == tick and "etag" not in forced.json()
    assert forced.headers["etag"] != first.headers["etag"]
    replaced = client.get(path, headers=headers)  # the old ETag no longer matches the replaced result
    assert replaced.status_code == 200 and replaced.json()["cached"] is True
    monkeypatch.setattr(data, "_cache", {})  # restart, expiry or eviction also requires a result
    assert client.get(path, headers=headers).json()["cached"] is False


def test_refresh_checks_are_scoped_and_bypass_display_cache(api, monkeypatch):
    import app as portal_app

    client, tables = api
    datasets = portal_app.LIVE["daily-orders"].datasets
    left = "core.orders.daily_orders"
    right = "core.orders.order_exceptions"
    monkeypatch.setattr(datasets["orders"], "sql", f"SELECT * FROM {left}")
    monkeypatch.setattr(datasets["exceptions"], "sql", f"SELECT * FROM {left} JOIN {right} USING (id)")
    tables.infos[right] = table(1_795_000_000_000)
    path = "/api/d/daily-orders/sources"
    assert client.get(path).status_code == 200  # populate the display cache
    tables.calls.clear()
    tables.infos[left] = table(1_796_000_000_000)
    checks = client.get(path + "?check=orders&check=exceptions&check=secret&check=orders").json()["checks"]
    assert tables.calls.count(left) == tables.calls.count(right) == 1
    assert "main_prod.ops.secret_vw" not in tables.calls
    assert checks == {"orders": 1_796_000_000, "exceptions": 1_796_000_000}


@pytest.mark.parametrize("sql,refresh,dynamic_default,expected", [
    ("SELECT * FROM samples.tpch.orders", "changed", False, 0),
    ("SELECT * FROM samples.tpch.orders", "always", False, None),
    ("SELECT * FROM samples.tpch.orders WHERE x <= current_date()", "changed", False, None),
    ("SELECT unix_timestamp() FROM samples.tpch.orders", "changed", False, None),
    ("SELECT * FROM samples.tpch.orders WHERE x <= :date", "changed", True, None),
    ("SELECT * FROM samples.tpch.orders, core.orders.order_exceptions", "changed", False, None),
    ("SELECT * FROM main_prod.operations.daily_orders_vw", "changed", False, None),
    ("SELECT * FROM core.orders.order_exceptions", "changed", False, None),
])
def test_refresh_checks_fall_back_for_opaque_sources(api, monkeypatch, sql, refresh, dynamic_default, expected):
    import app as portal_app

    client, _ = api
    board = portal_app.LIVE["daily-orders"]
    ds = board.datasets["orders"]
    monkeypatch.setattr(ds, "sql", sql)
    monkeypatch.setattr(ds, "refresh", refresh)
    if dynamic_default:
        monkeypatch.setattr(ds, "params", ["date"])
        monkeypatch.setitem(board.params, "date", {"type": "DATE", "default": "@today"})
    response = client.get("/api/d/daily-orders/sources?check=orders")
    assert response.json()["checks"] == {"orders": expected}


def test_sources_lists_only_datasets_the_viewer_may_open(api):
    client, tables = api
    res = client.get("/api/d/daily-orders/sources")
    assert res.status_code == 200
    got = res.json()["datasets"]
    assert set(got) == {"orders", "exceptions"}  # not "secret"
    assert "main_prod.ops.secret_vw" not in tables.calls
    assert got["orders"]["tables"] == [M("core.orders.daily_orders", 1_794_000_000)]
    assert got["orders"]["source_updated_at"] == 1_794_000_000 and "06:00" in got["orders"]["source_note"]
    # no permission on one table: that table is unknown, and the request still succeeds
    assert got["exceptions"]["tables"] == [U("core.orders.order_exceptions")]
    assert got["exceptions"]["source_updated_at"] is None


def test_sources_refuses_people_outside_the_dashboard_groups(api, monkeypatch, tmp_path):
    import app as portal_app
    from portal.auth import User
    folder = write_dashboard(tmp_path / "more", "analysts-only", "title: A\ngroups: [analysts]\ndatasets:\n  x: {sql: sql/x.sql}\n",
                             {"x": "SELECT * FROM samples.tpch.orders"})
    restricted = load_dashboard(folder, env="prod")
    assert restricted.groups == ["analysts"] and restricted.errors == []
    monkeypatch.setitem(portal_app.LIVE, restricted.slug, restricted)
    assert api[0].get("/api/d/analysts-only/sources").status_code == 403
    monkeypatch.setattr(portal_app, "current_user", lambda request: User(key="u", email="x", groups=frozenset(), client=None))
    assert api[0].get("/api/d/nope/sources").status_code == 404


def test_page_config_carries_cache_type_source_and_the_label(api):
    client, _ = api
    page = client.get("/d/daily-orders").text
    assert '"cache": "app"' in page and "Daily orders" in page
    assert 'id="pn-fresh"' in page and 'aria-controls="pn-fresh-panel"' in page
    assert 'id="pn-fresh"' not in client.get("/").text  # no label on the home page
