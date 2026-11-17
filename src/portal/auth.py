"""Who is calling: the forwarded user token in Databricks Apps, or a local CLI profile in development."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from fastapi import HTTPException, Request

LOCAL_PROFILE = os.getenv("PORTAL_LOCAL_PROFILE")  # set only by scripts/run_local.ps1 / run_local.sh
_IDENTITY_TTL = 600
_identities: dict[str, tuple[float, "User"]] = {}


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
        cache_key = token[-24:]
        make = lambda: WorkspaceClient(host=_host(), token=token, auth_type="pat")  # noqa: E731
    elif LOCAL_PROFILE:
        cache_key = f"profile:{LOCAL_PROFILE}"
        make = lambda: WorkspaceClient(profile=LOCAL_PROFILE)  # noqa: E731
    else:
        raise HTTPException(401, "No user token. Open the portal through Databricks Apps.")
    hit = _identities.get(cache_key)
    if hit and hit[0] > time.time():
        return hit[1]
    client = make()
    me = client.current_user.me()
    user = User(key=me.id or me.user_name, email=me.user_name or "", groups=frozenset(g.display for g in (me.groups or []) if g.display),
                client=client)
    _identities[cache_key] = (time.time() + _IDENTITY_TTL, user)
    return user


def can_open(user: User, groups: list[str]) -> bool:
    return not groups or bool(user.groups & set(groups))
