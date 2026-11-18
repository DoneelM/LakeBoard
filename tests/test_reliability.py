"""Security boundary, warm scheduling and event-date coverage, without a workspace."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from databricks.sdk.errors import PermissionDenied

from portal import access, data
from portal.registry import Dataset, load_dashboard


def dataset(**extra):
    return Dataset(id="x", title="X", sql="SELECT o_orderdate FROM samples.tpch.orders WHERE o_orderkey = :id -- end",
                   params=["id"], cache_ttl=60, auth="user", shared=True, **extra)


def board(ds):
    return SimpleNamespace(slug="test", params={"id": {"type": "INT", "default": "1"}}, datasets={"x": ds})


def test_shared_check_binds_full_query_and_isolates_viewers_parameters_and_sql(monkeypatch):
    ds, guard, calls = dataset(), access.SharedAccess(), []
    monkeypatch.setattr(data, "run_sql", lambda c, sql, p: calls.append((c, sql, p)))
    guard.check(board(ds), ds, "reader", "u1", {})
    guard.check(board(ds), ds, "reader", "u1", {})
    assert len(calls) == 1 and calls[0][0] == "reader"
    assert calls[0][1].endswith("-- end\n) AS lakeboard_access LIMIT 0")
    assert (calls[0][2][0].type, calls[0][2][0].value) == ("INT", "1")
    guard.check(board(ds), ds, "reader", "u2", {})
    guard.check(board(ds), ds, "reader", "u1", {"id": "2"})
    ds.sql += "\n "
    guard.check(board(ds), ds, "reader", "u1", {})
    assert len(calls) == 4


def test_allowed_check_expires_and_revocation_is_denied(monkeypatch):
    ds, guard, calls, clock = dataset(), access.SharedAccess(), [], [100.0]
    monkeypatch.setattr(access.time, "monotonic", lambda: clock[0])
    def run(*args):
        calls.append(1)
        if len(calls) > 1:
            raise PermissionDenied("private workspace error")
    monkeypatch.setattr(data, "run_sql", run)
    guard.check(board(ds), ds, None, "u", {})
    clock[0] += 301
    with pytest.raises(access.AccessDenied):
        guard.check(board(ds), ds, None, "u", {})
    with pytest.raises(access.AccessDenied):
        guard.check(board(ds), ds, None, "u", {})
    assert len(calls) == 2
    clock[0] += 61
    with pytest.raises(access.AccessDenied):
        guard.check(board(ds), ds, None, "u", {})
    assert len(calls) == 3


@pytest.mark.parametrize("failure, expected", [
    (data.QueryError("[INSUFFICIENT_PERMISSIONS] private"), access.AccessDenied),
    (data.QueryError("private", "PERMISSION_DENIED"), access.AccessDenied),
    (data.QueryError("warehouse down"), access.AccessUnavailable),
    (TimeoutError("private connection details"), access.AccessUnavailable),
])
def test_probe_errors_fail_closed_without_leaking_backend_details(monkeypatch, failure, expected):
    ds, guard, calls = dataset(), access.SharedAccess(), []
    def run(*args):
        calls.append(1)
        raise failure
    monkeypatch.setattr(data, "run_sql", run)
    for _ in range(2):
        with pytest.raises(expected) as err:
            guard.check(board(ds), ds, None, "u", {})
        assert "private" not in str(err.value)
    assert len(calls) == (1 if expected is access.AccessDenied else 2)


def test_concurrent_requests_coalesce_and_cache_is_bounded(monkeypatch):
    ds, guard, calls = dataset(), access.SharedAccess(), []
    guard.MAX_ENTRIES = 2
    monkeypatch.setattr(data, "run_sql", lambda *args: calls.append(1))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: guard.check(board(ds), ds, None, "u", {}), range(20)))
    assert len(calls) == 1
    for n in range(5):
        guard.check(board(ds), ds, None, f"u{n}", {})
    assert len(guard._entries) == 2


def test_route_refuses_cache_hit_and_refresh_before_fetch(monkeypatch):
    import app
    from fastapi.testclient import TestClient
    from portal.auth import User
    ds = dataset()
    monkeypatch.setattr(app, "board_for", lambda *a: (board(ds), User("reader", "reader@example.com", frozenset(), None)))
    guard = access.SharedAccess()
    monkeypatch.setattr(access, "SHARED_ACCESS", guard)
    monkeypatch.setattr(data, "run_sql", lambda *a: (_ for _ in ()).throw(PermissionDenied("denied")))
    monkeypatch.setattr(data, "fetch", lambda *a: pytest.fail("must not consult the shared result cache"))
    client = TestClient(app.app)
    for suffix in ("", "?refresh=1"):
        r = client.get("/api/d/test/data/x" + suffix, headers={"If-None-Match": '"123.0"'})
        assert r.status_code == 403 and "rows" not in r.json()
        assert "no-store" in r.headers["cache-control"]


def test_failed_dataset_query_logs_statement_without_sql_or_values(monkeypatch, caplog):
    from types import SimpleNamespace

    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    reply = SimpleNamespace(
        statement_id="test-statement", status=SimpleNamespace(
            state=StatementState.FAILED, error=SimpleNamespace(message="private error", error_code="BAD_REQUEST"),
        ),
    )
    client = SimpleNamespace(statement_execution=SimpleNamespace(execute_statement=lambda **kwargs: reply))
    monkeypatch.setattr(data, "WAREHOUSE_ID", "test-warehouse")
    params = [StatementParameterListItem(name="filter", value="private value")]
    with caplog.at_level("INFO", logger="portal.data"), pytest.raises(data.QueryError):
        data.run_sql(client, "SELECT :filter", params, dataset="test/x")
    assert "dataset=test/x statement_id=test-statement elapsed_ms=" in caplog.text
    assert "outcome=failed" in caplog.text
    assert all(text not in caplog.text for text in ("SELECT", "private value", "private error"))


@pytest.mark.parametrize("auth,shared,todo", [("app", True, False), ("user", False, False), ("user", True, True)])
def test_non_shared_modes_do_not_probe(monkeypatch, auth, shared, todo):
    ds = dataset()
    ds.auth, ds.shared, ds.todo = auth, shared, todo
    monkeypatch.setattr(data, "run_sql", lambda *a: pytest.fail("no probe in this mode"))
    access.SharedAccess().check(board(ds), ds, None, "u", {})


def test_startup_warming_does_not_repeat_on_schedule(monkeypatch):
    startup = Dataset("startup", "S", "SELECT 1", [], 60, "user", shared=True, warm=[{}], warm_at="startup")
    regular = Dataset("regular", "R", "SELECT 1", [], 60, "user", shared=True, warm=[{}])
    todo = Dataset("todo", "T", "", [], 60, "user", shared=True, warm=[{}], todo=True)
    d = SimpleNamespace(slug="warm", datasets={s.id: s for s in (startup, regular, todo)})
    calls, tick = [], [0]
    monkeypatch.setattr(data, "WARM_ENABLED", True)
    monkeypatch.setattr(data, "WARM", {"environments": ["prod"]})
    monkeypatch.setattr(data, "_warm_slot", lambda: "morning" if tick[0] == 0 else "afternoon")
    monkeypatch.setattr(data, "fetch", lambda d, ds, *a: calls.append(ds.id))
    async def sleep(_):
        tick[0] += 1
        if tick[0] == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(data.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(data.warm_datasets({"warm": d}, lambda: None, "prod"))
    assert calls == ["startup", "regular", "regular"]


@pytest.mark.parametrize("value,extra,error", [("startup", "", "needs a warm"), ("daily", "warm: [{}]", "must be schedule or startup")])
def test_manifest_rejects_invalid_warm_mode(make_dashboard, value, extra, error):
    manifest = f"title: Test\ndatasets:\n  x:\n    sql: sql/x.sql\n    cache: shared\n    warm_at: {value}\n    {extra}\n"
    d = load_dashboard(make_dashboard("test", manifest, {"x": "SELECT 1"}), env="prod")
    assert any(error in e for e in d.errors)


def test_event_coverage_uses_returned_dates_and_never_falls_back_to_today():
    ds = dataset(data_through="event_day")
    assert data.data_through(ds, {"columns": ["event_day"], "rows": [["2024-02-01"], [None], ["bad"], ["2023-01-01"]]}) == "2024-02-01"
    assert data.data_through(ds, {"columns": ["other"], "rows": [["2025-01-01"]]}) is None
    assert data.data_through(ds, {"columns": ["event_day"], "rows": []}) is None
