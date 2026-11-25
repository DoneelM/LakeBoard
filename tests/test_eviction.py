"""Caches that must not grow without limit, and the start-up check on an unknown workspace host."""
from types import SimpleNamespace

import pytest

from portal import auth, data, settings


@pytest.fixture()
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(time=lambda: now[0]))
    monkeypatch.setattr(data.time, "time", lambda: now[0])
    return now


@pytest.fixture()
def identities(monkeypatch):
    monkeypatch.setattr(auth, "_identities", {})


@pytest.fixture()
def caches(monkeypatch):
    monkeypatch.setattr(data, "_cache", {})
    monkeypatch.setattr(data, "_locks", {})


def sign_in(monkeypatch, token):
    me = SimpleNamespace(id=token, user_name=token, groups=[])
    monkeypatch.setattr(auth, "WorkspaceClient", lambda **kw: SimpleNamespace(current_user=SimpleNamespace(me=lambda: me)))
    return auth.current_user(SimpleNamespace(headers={"x-forwarded-access-token": token}))


def test_identities_stay_bounded_as_time_advances(monkeypatch, clock, identities):
    for i in range(50):
        sign_in(monkeypatch, f"token-{i}")
        clock[0] += auth._IDENTITY_TTL + 1
    assert len(auth._identities) == 1


def test_expired_identity_is_evicted_by_another_users_request(monkeypatch, clock, identities):
    sign_in(monkeypatch, "alice")
    clock[0] += auth._IDENTITY_TTL + 1
    sign_in(monkeypatch, "bob")
    assert [u.email for _, u in auth._identities.values()] == ["bob"]


def test_unexpired_identities_are_kept(monkeypatch, clock, identities):
    sign_in(monkeypatch, "alice")
    sign_in(monkeypatch, "bob")
    assert {u.email for _, u in auth._identities.values()} == {"alice", "bob"}


def test_concurrent_eviction_of_one_expired_identity_does_not_raise(monkeypatch, clock, identities):
    from concurrent.futures import ThreadPoolExecutor
    sign_in(monkeypatch, "alice")
    clock[0] += auth._IDENTITY_TTL + 1
    req = SimpleNamespace(headers={"x-forwarded-access-token": "alice"})
    with ThreadPoolExecutor(16) as pool:
        for f in [pool.submit(auth.current_user, req) for _ in range(64)]:
            f.result()  # re-raises a KeyError from a double delete


def test_locks_stay_bounded_as_cache_keys_expire(clock, caches):
    for i in range(50):
        data._cache[f"k{i}"] = (clock[0], clock[0], {})
        data._lock(f"k{i}")
    clock[0] += 3601
    data.prune()
    assert not data._cache and not data._locks


def test_prune_keeps_locks_for_cached_and_in_flight_keys(clock, caches):
    data._cache["cached"] = (clock[0] + 60, clock[0], {})
    cached, busy = data._lock("cached"), data._lock("busy")
    data._lock("idle")
    with busy:  # a first fetch still running has a lock but no cache entry yet
        data.prune()
    assert data._locks == {"cached": cached, "busy": busy}


@pytest.fixture()
def hosts(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENTS", {"dev": {"host": "dev.example.net"}, "prod": {"host": "prod.example.net"}})


def test_unmatched_host_without_portal_env_raises(hosts, monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://typo.example.net/")
    with pytest.raises(ValueError, match="typo.example.net"):
        settings.current_env()


def test_no_host_and_no_portal_env_is_prod(hosts, monkeypatch):
    assert settings.current_env() == "prod"
    monkeypatch.setenv("DATABRICKS_HOST", "   ")
    assert settings.current_env() == "prod"


def test_portal_env_wins_over_unmatched_host(hosts, monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "typo.example.net")
    monkeypatch.setenv("PORTAL_ENV", "dev")
    assert settings.current_env() == "dev"


def test_matching_host_picks_its_environment(hosts, monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "HTTPS://Dev.Example.net//")
    assert settings.current_env() == "dev"
