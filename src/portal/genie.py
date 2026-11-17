"""Ask Genie: questions about a dashboard, answered by its Genie space through the Genie Conversation API.

Every call runs as the viewing user (their forwarded token, or the local CLI profile), never as the app's service
principal, so Genie only sees the data that person may see. The Conversation API has no field for context, so the
portal puts a short plain-text preamble (dashboard, filters, current view) in front of the question: on the first
message of a conversation, and again only when that context has changed. See docs/DESIGN.md.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import (BadRequest, DatabricksError, InvalidParameterValue, NotFound, PermissionDenied,
                                   ResourceDoesNotExist, ResourceExhausted, TooManyRequests, Unauthenticated)
from databricks.sdk.service.dashboards import GenieFeedbackRating

from .registry import Dashboard

ID_RE = re.compile(r"^[0-9a-f]{32}$")  # conversation and message ids, like space ids
ATTACHMENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")

MAX_QUESTION = 1000
MAX_CONTEXT_ITEMS = 20
MAX_KEY = 40
MAX_VALUE = 200
MAX_ROWS = 200
MAX_CELL = 500
MAX_TEXT = 8000
MAX_SQL = 20000
MAX_SUGGESTIONS = 5
RETRY_SECONDS = 15  # the SDK retries 429/503 by itself; keep that short so a busy Genie answers "busy" quickly

WORKING = {"SUBMITTED", "FILTERING_CONTEXT", "FETCHING_METADATA", "ASKING_AI", "PENDING_WAREHOUSE", "EXECUTING_QUERY"}
DONE = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}

NO_ACCESS = "You can't use Genie for this dashboard yet. Ask the data team for access to its Genie space."
NO_CONSENT = ("The portal doesn't have your permission to use Genie yet. Reload the portal and accept the prompt; "
              "if there is no prompt, ask the data team.")
BUSY = "Genie is busy. Try again in a minute."
UNAVAILABLE = "Genie isn't answering right now. Try again in a few minutes."
GONE = "This conversation is no longer available. Start a new chat."


class GenieProblem(Exception):
    """A Genie-side failure, already turned into a status code and a plain message for the viewer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def client_for(user_client: WorkspaceClient) -> WorkspaceClient:
    """A copy of the viewer's client with a short retry budget (same identity, same token)."""
    cfg = user_client.config.copy()
    cfg.retry_timeout_seconds = RETRY_SECONDS
    return WorkspaceClient(config=cfg)


# ---------- input cleaning ----------

def clean_text(value, limit: int) -> str:
    """One line of plain text: control characters and line breaks removed, spaces collapsed, cut to `limit`."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join(CONTROL_RE.sub(" ", str(value)).split())[:limit].strip()


def clean_question(value) -> str:
    if not isinstance(value, str):
        return ""
    text = CONTROL_RE.sub(lambda m: "\n" if m.group(0) == "\n" else " ", value.replace("\r\n", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def clean_context(raw) -> dict[str, str]:
    """The page's description of its current view: at most 20 short label -> text pairs, plain text only."""
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if len(out) >= MAX_CONTEXT_ITEMS:
            break
        key, value = clean_text(k, MAX_KEY), clean_text(v, MAX_VALUE)
        if key and value and key not in out:
            out[key] = value
    return out


def clean_params(dashboard: Dashboard, raw) -> dict[str, str]:
    """Only the SQL parameters declared in dashboard.yml, as short text."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in dashboard.params:
        value = clean_text(raw.get(name), MAX_VALUE)
        if value:
            out[name] = value
    return out


# ---------- the context preamble ----------

def context_block(dashboard: Dashboard, params: dict[str, str], context: dict[str, str]) -> str:
    about = dashboard.genie.about if dashboard.genie else ""
    lines = ["[Context from the dashboard the question was asked on. It is not part of the question.]",
             f"Dashboard: {clean_text(dashboard.title, 120)}." + (f" {about}" if about else "")]
    if params:
        lines.append("Dashboard filters: " + "; ".join(f"{k} = {v}" for k, v in params.items()) + ".")
    if context:
        lines.append("Current view of the dashboard: " + "; ".join(f"{k} = {v}" for k, v in context.items()) + ".")
    if params or context:
        lines.append("Apply these as filters unless the question says otherwise.")
    return "\n".join(lines)


def message_text(block: str | None, question: str) -> str:
    return f"{block}\n\nQuestion: {question}" if block else question


class SentContext:
    """Remembers, per viewer and conversation, which context was last sent, so it is only repeated when it changes.

    In memory only: after a restart the context is simply sent again with the next question."""

    def __init__(self, size: int = 5000):
        self._seen: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._size = size
        self._guard = threading.Lock()

    @staticmethod
    def digest(block: str) -> str:
        return hashlib.sha256(block.encode("utf-8")).hexdigest()

    def changed(self, user_key: str, conversation_id: str, block: str) -> bool:
        with self._guard:
            return self._seen.get((user_key, conversation_id)) != self.digest(block)

    def remember(self, user_key: str, conversation_id: str, block: str) -> None:
        with self._guard:
            self._seen[(user_key, conversation_id)] = self.digest(block)
            self._seen.move_to_end((user_key, conversation_id))
            while len(self._seen) > self._size:
                self._seen.popitem(last=False)


SENT = SentContext()


# ---------- Genie calls (blocking; the app runs them with asyncio.to_thread) ----------

def problem_from(e: BaseException) -> GenieProblem:
    """Turns an SDK error into a plain message. Nothing from Genie ever becomes a 500."""
    cause = e.__cause__ if isinstance(e, TimeoutError) and e.__cause__ else e
    text = str(cause).lower()
    if isinstance(cause, (TooManyRequests, ResourceExhausted)) or isinstance(e, TimeoutError) and "429" in text:
        return GenieProblem(429, BUSY)
    if isinstance(cause, (PermissionDenied, Unauthenticated)):
        return GenieProblem(403, NO_CONSENT if "scope" in text else NO_ACCESS)
    if isinstance(cause, (NotFound, ResourceDoesNotExist)):
        return GenieProblem(404, GONE)
    if isinstance(cause, (BadRequest, InvalidParameterValue)):
        return GenieProblem(400, "Genie couldn't accept that question. Try rewording it.")
    return GenieProblem(503, UNAVAILABLE)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (DatabricksError, TimeoutError, OSError, ValueError) as e:
        raise problem_from(e) from e


def ask(client: WorkspaceClient, space_id: str, conversation_id: str | None, content: str) -> dict:
    """Starts or continues a conversation without waiting for the answer."""
    if conversation_id:
        waiter = _call(client.genie.create_message, space_id, conversation_id, content)
    else:
        waiter = _call(client.genie.start_conversation, space_id, content)
    resp = waiter.response
    conv = getattr(resp, "conversation_id", None) or conversation_id
    msg = getattr(resp, "message_id", None) or getattr(resp, "id", None)
    if not (conv and msg and ID_RE.match(conv) and ID_RE.match(msg)):
        raise GenieProblem(503, UNAVAILABLE)
    return {"conversation_id": conv, "message_id": msg}


def _cell(v):
    return None if v is None else str(v)[:MAX_CELL]


def _rows(client: WorkspaceClient, space_id: str, conversation_id: str, message_id: str, attachment_id: str) -> dict:
    res = _call(client.genie.get_message_attachment_query_result, space_id, conversation_id, message_id, attachment_id)
    st = res.statement_response
    if not st or not st.manifest or not st.manifest.schema:
        return {"columns": [], "rows": [], "truncated": False}
    columns = [str(c.name) for c in (st.manifest.schema.columns or [])]
    data = list((st.result and st.result.data_array) or [])
    total = st.manifest.total_row_count or len(data)
    truncated = len(data) > MAX_ROWS or total > len(data) or bool(st.manifest.truncated)
    return {"columns": columns, "rows": [[_cell(v) for v in row] for row in data[:MAX_ROWS]], "truncated": truncated}


def poll(client: WorkspaceClient, space_id: str, conversation_id: str, message_id: str) -> dict:
    """The message's state; once complete, the answer text, SQL and (capped) result rows."""
    m = _call(client.genie.get_message, space_id, conversation_id, message_id)
    status = m.status.value if m.status else "SUBMITTED"
    out = {"status": status, "text": "", "sql": "", "description": "", "suggested_questions": [], "columns": [],
           "rows": [], "truncated": False, "error": ""}
    texts, query_attachment = [], None
    for a in m.attachments or []:
        if a.text and a.text.content:
            texts.append(a.text.content)
        if a.query and query_attachment is None:
            query_attachment = a
        if a.suggested_questions and a.suggested_questions.questions:
            out["suggested_questions"] = [clean_text(q, 200) for q in a.suggested_questions.questions if clean_text(q, 200)][:MAX_SUGGESTIONS]
    out["text"] = "\n\n".join(texts)[:MAX_TEXT]
    if query_attachment:
        q = query_attachment.query
        out["sql"] = (q.query or "")[:MAX_SQL]
        out["description"] = (q.description or "")[:MAX_TEXT]
    if status == "FAILED":
        detail = clean_text(m.error.error if m.error else "", 300)
        out["error"] = "Genie couldn't answer that." + (f" {detail}" if detail else "")
    elif status == "CANCELLED":
        out["error"] = "This question was cancelled."
    elif status == "QUERY_RESULT_EXPIRED":
        out["error"] = "The result of this question has expired. Ask it again to see the rows."
    elif status == "COMPLETED" and query_attachment and query_attachment.attachment_id:
        if ATTACHMENT_RE.match(query_attachment.attachment_id):
            try:
                out.update(_rows(client, space_id, conversation_id, message_id, query_attachment.attachment_id))
            except GenieProblem as p:  # the answer is still useful without its rows
                out["error"] = "Genie answered, but the result rows couldn't be loaded. " + p.message
    return out


def feedback(client: WorkspaceClient, space_id: str, conversation_id: str, message_id: str, rating: str) -> None:
    value = {"up": GenieFeedbackRating.POSITIVE, "down": GenieFeedbackRating.NEGATIVE}[rating]
    _call(client.genie.send_message_feedback, space_id, conversation_id, message_id, value)
