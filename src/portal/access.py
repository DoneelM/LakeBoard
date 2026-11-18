"""Authorize a shared result as its reader before consulting the result cache.

Analyze the complete query, including columns and bound parameters, without returning rows.
This is a permission check, not a way to apply row filters or masks to someone else's result.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict

from databricks.sdk.errors import PermissionDenied

from . import data


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
        signature = json.dumps([data.WAREHOUSE_ID, ds.sql, [(p.name, p.type, p.value) for p in params]])
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
                    marker in str(exc).upper() for marker in ("INSUFFICIENT_PERMISSIONS", "SQLSTATE: 42501", "[PERMISSION_DENIED]")
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
