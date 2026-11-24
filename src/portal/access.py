"""Authorize a shared result as its reader before consulting the result cache.

Analyze the complete query, including columns and bound parameters, without returning rows.
This is a permission check, not a way to apply row filters or masks to someone else's result.

A decision is remembered per viewer, warehouse, SQL text and parameter names and types, but not parameter values:
bound values cannot change which objects a query reads, so a new filter value reuses the decision. The exception
is a parameter that names an object or a location (inside IDENTIFIER(...) or a table function that reads by name
or path); those values stay in the key. Unity Catalog reports objects a reader may not see as *_NOT_FOUND, so
those error classes count as a denial (decision 0013).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict

from databricks.sdk.errors import PermissionDenied

from . import data
from .registry import PARAM_RE, strip_sql_comments_and_strings

# Error markers that mean "this reader may not read it". Unity Catalog answers *_NOT_FOUND for objects a reader
# can't see, so those count as denials too. A dropped object reads the same, and its own query would fail anyway.
DENIED_MARKERS = (
    "INSUFFICIENT_PERMISSIONS", "SQLSTATE: 42501", "[PERMISSION_DENIED]",
    "TABLE_OR_VIEW_NOT_FOUND", "SCHEMA_NOT_FOUND", "CATALOG_NOT_FOUND",
)
# Calls whose arguments can choose which object or location is read, so their parameter values change the check.
NAMING_CALL_RE = re.compile(r"\b(?:IDENTIFIER|READ_\w+|TABLE_CHANGES|EVENT_LOG|CLOUD_FILES_STATE)\s*\(", re.IGNORECASE)


def naming_params(sql: str) -> set[str]:
    """Parameters used inside a call that can choose which object or location the query reads."""
    body = strip_sql_comments_and_strings(sql)
    names = set()
    for match in NAMING_CALL_RE.finditer(body):
        depth, end = 1, match.end()
        while end < len(body) and depth:
            depth += {"(": 1, ")": -1}.get(body[end], 0)
            end += 1
        names.update(PARAM_RE.findall(body[match.end():end]))
    return names


class AccessDenied(Exception):
    pass


class AccessUnavailable(Exception):
    pass


class SharedAccess:
    ALLOW_TTL = 300
    DENY_TTL = 60
    MAX_ENTRIES = 4096

    def __init__(self):
        self._entries = OrderedDict()
        self._guard = threading.Lock()
        # Fixed-size locks bound memory and coalesce concurrent checks for the same key.
        self._locks = [threading.Lock() for _ in range(64)]

    def check(self, dashboard, ds, client, viewer: str, raw: dict) -> None:
        if not ds.shared or ds.auth == "app" or ds.todo:
            return
        params = data.bind(dashboard, ds, raw)
        naming = naming_params(ds.sql)
        signature = json.dumps([data.WAREHOUSE_ID, ds.sql, [(p.name, p.type) for p in params],
                                [(p.name, p.value) for p in params if p.name in naming]])
        key = (viewer, hashlib.sha256(signature.encode()).hexdigest())
        with self._locks[int(key[1][:8], 16) % len(self._locks)]:
            with self._guard:
                hit = self._entries.get(key)
                if hit and hit[0] > time.monotonic():
                    self._entries.move_to_end(key)
                else:
                    hit = None
            if hit:
                if not hit[1]:
                    raise AccessDenied("You don't have access to the data behind this section.")
                return
            try:
                # The newline matters when the dataset ends in a -- comment.
                data.run_sql(client, f"SELECT * FROM (\n{ds.sql}\n) AS lakeboard_access LIMIT 0", params)
            except (PermissionDenied, data.QueryError) as exc:
                code = str(getattr(exc, "code", "") or "").upper()
                denied = isinstance(exc, PermissionDenied) or code == "PERMISSION_DENIED" or any(
                    marker in str(exc).upper() for marker in DENIED_MARKERS
                )
                if not denied:
                    raise AccessUnavailable("Couldn't verify your data access. Try again shortly.") from None
                allowed = False
            except Exception:
                # Network, warehouse and authentication failures must never fall through to cached rows.
                raise AccessUnavailable("Couldn't verify your data access. Try again shortly.") from None
            else:
                allowed = True
            ttl = self.ALLOW_TTL if allowed else self.DENY_TTL
            with self._guard:
                self._entries[key] = (time.monotonic() + ttl, allowed)
                self._entries.move_to_end(key)
                while len(self._entries) > self.MAX_ENTRIES:
                    self._entries.popitem(last=False)
            if not allowed:
                raise AccessDenied("You don't have access to the data behind this section.")


SHARED_ACCESS = SharedAccess()
