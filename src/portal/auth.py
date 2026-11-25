"""Who is calling: the forwarded user token in Databricks Apps, or a local CLI profile in development."""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from fastapi import HTTPException, Request

LOCAL_PROFILE = os.getenv("PORTAL_LOCAL_PROFILE")  # set only by scripts/run_local.ps1 / run_local.sh
_IDENTITY_TTL = 60  # seconds; a removed group membership stops counting within a minute
_identities: dict[str, tuple[float, "User"]] = {}
_identities_guard = threading.Lock()  # all reads and writes; list(items()) is not safe against a concurrent insert


@dataclass(frozen=True)
class User:
    key: str  # cache key: the user's id
    email: str
    groups: frozenset[str]
    client: WorkspaceClient  # acts as this user


def _host() -> str:
    host = os.getenv("DATABRICKS_HOST", "")
    return host if host.startswith("http") else f"https://{host}"


def current_user(request: Request) -> User:
    token = request.headers.get("x-forwarded-access-token")
    if token:
        cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()  # the whole token, never kept as is
        make = lambda: WorkspaceClient(host=_host(), token=token, auth_type="pat")  # noqa: E731
    elif LOCAL_PROFILE:
        cache_key = f"profile:{LOCAL_PROFILE}"
        make = lambda: WorkspaceClient(profile=LOCAL_PROFILE)  # noqa: E731
    else:
        raise HTTPException(401, "No user token. Open the portal through Databricks Apps.")
    now = time.monotonic()
    with _identities_guard:
        for k, v in list(_identities.items()):  # snapshot under the lock: a concurrent insert cannot change the dict mid-loop
            if v[0] <= now:  # expired entries still hold a client and token
                _identities.pop(k, None)
        hit = _identities.get(cache_key)
        if hit and hit[0] > now:
            return hit[1]
    client = make()  # Databricks call stays outside the lock
    me = client.current_user.me()
    user = User(key=me.id or me.user_name, email=me.user_name or "", groups=frozenset(g.display for g in (me.groups or []) if g.display),
                client=client)
    with _identities_guard:
        hit = _identities.get(cache_key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        _identities[cache_key] = (time.monotonic() + _IDENTITY_TTL, user)
        return user


def can_open(user: User, groups: list[str]) -> bool:
    return not groups or bool(user.groups & set(groups))


def can_open_dashboard(user: User, board, drafts_groups: list[str] = (), local: bool = False) -> bool:
    """Whether this person may open a dashboard. A live one follows its `groups` ([] = everyone). A draft
    (`status: draft`) is only for `drafts_groups` (src/environments.yml) plus its own `groups`; an empty list there
    means nobody, never everyone. A local run shows drafts to the person running it, as the same `groups` check."""
    if not getattr(board, "draft", False) or local:
        return can_open(user, board.groups)
    return bool(user.groups & (set(drafts_groups) | set(board.groups)))
