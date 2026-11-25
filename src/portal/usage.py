"""Page-view events: always one line in the app log; in prod also rows in the usage table (src/environments.yml).

Rows are written in batches by the app's service principal, which needs MODIFY on the table
(scripts/grant_app_access.py). A failed write is logged and dropped; it never affects a page.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import threading
import time

from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from .settings import USAGE_TABLES

log = logging.getLogger("portal.usage")
TABLE_NAME_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*\.[A-Za-z_]\w*$")
COLUMNS = ("event_time", "event", "environment", "dashboard", "user_email")
MAX_BATCH = 200
MAX_QUEUE = 5000

_queue: list[tuple] = []
_guard = threading.Lock()


def table_for(env: str) -> str | None:
    name = USAGE_TABLES.get(env)
    if name and not TABLE_NAME_RE.fullmatch(name):
        raise ValueError(f"usage_table for {env} must be catalog.schema.table, got {name!r}")
    return name


def record(event: str, env: str, user_email: str, dashboard: str | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    log.info(json.dumps({"event": event, "env": env, "user": user_email, "ts": round(now.timestamp()), "dashboard": dashboard}))
    if table_for(env):
        with _guard:
            if len(_queue) < MAX_QUEUE:
                _queue.append((now.strftime("%Y-%m-%d %H:%M:%S"), event, env, dashboard, user_email))


def _insert(client, warehouse_id: str, table: str, rows: list[tuple]) -> None:
    if not TABLE_NAME_RE.fullmatch(table):
        raise ValueError("Usage table must be a catalog.schema.table name")
    params = [StatementParameterListItem(name="usage_table", type="STRING", value=table)]
    values = []
    for i, row in enumerate(rows):
        values.append("(" + ", ".join(f":{c}{i}" for c in COLUMNS) + ")")
        for col, value in zip(COLUMNS, row, strict=True):
            params.append(StatementParameterListItem(name=f"{col}{i}", type="TIMESTAMP" if col == "event_time" else "STRING", value=value))
    # Only the fixed column list and generated parameter markers build SQL text.
    sql = "INSERT INTO IDENTIFIER(:usage_table) (" + ", ".join(COLUMNS) + ") VALUES " + ", ".join(values)
    r = client.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse_id, parameters=params, wait_timeout="50s")
    deadline = time.time() + 120
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING) and time.time() < deadline:
        time.sleep(2)
        r = client.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error.message if r.status.error else str(r.status.state))


async def flush_loop(app_client_factory, warehouse_id: str, env: str) -> None:
    table = table_for(env)
    if not table or not warehouse_id:
        return
    while True:
        await asyncio.sleep(60)
        with _guard:
            batch, _queue[:] = _queue[:MAX_BATCH], _queue[MAX_BATCH:]
        if not batch:
            continue
        try:
            await asyncio.to_thread(_insert, app_client_factory(), warehouse_id, table, batch)
        except Exception as e:  # usage is best-effort
            log.warning("could not write %d usage rows to %s: %s", len(batch), table, str(e)[:300])
