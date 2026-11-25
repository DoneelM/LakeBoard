import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from portal.registry import load_all, load_dashboard, parse_ttl  # noqa: E402

BOARDS = load_all()  # the real dashboards under src/dashboards (only the two loops below use them)


def test_there_are_dashboards():
    assert BOARDS


@pytest.mark.parametrize("slug", sorted(BOARDS))
def test_dashboard_is_valid(slug):
    assert BOARDS[slug].errors == []


def test_parse_ttl():
    assert parse_ttl("15m") == 900
    assert parse_ttl("6h") == 21600
    assert parse_ttl(None) == 3600


def test_rejects_ddl_and_undeclared_params(tmp_path):
    d = tmp_path / "bad"
    (d / "sql").mkdir(parents=True)
    (d / "dashboard.yml").write_text("title: Bad\ndatasets:\n  x: {sql: sql/x.sql}\n")
    (d / "sql" / "x.sql").write_text("DROP TABLE t; SELECT * FROM t WHERE a = :undeclared")
    (d / "index.html").write_text("<script>dash.data('y')</script>")
    errs = " ".join(load_dashboard(d).errors)
    assert "DROP" in errs
    assert "undeclared" in errs
    assert "single statement" in errs
    assert "'y'" in errs


def test_rejects_other_catalogs_remote_scripts_and_bad_settings(tmp_path):
    d = tmp_path / "bad2"
    (d / "sql").mkdir(parents=True)
    manifest = ["title: Bad", "section: Nowhere", "environments: [uat]", "libs: [jquery]", "datasets:", "  x: {sql: sql/x.sql}"]
    (d / "dashboard.yml").write_text(chr(10).join(manifest))
    (d / "sql" / "x.sql").write_text(
        "WITH a AS (SELECT 1 AS n FROM samples.tpch.orders) "
        "SELECT * FROM a JOIN other_catalog.finance.t ON 1 = 1 JOIN finance.t2 ON 1 = 1 JOIN loose ON 1 = 1")
    (d / "index.html").write_text("<script src='https://evil.example/x.js'></script><script>dash.data('x')</script>")
    errs = " ".join(load_dashboard(d).errors)
    assert "catalog 'other_catalog' is not allowed" in errs
    assert "'finance.t2' must be written as catalog.schema.table" in errs
    assert "'loose' is not a CTE" in errs
    assert "samples" not in errs.replace("allowed: ['samples']", "")
    assert "script from another site" in errs
    assert "section 'Nowhere'" in errs and "'uat'" in errs and "'jquery'" in errs


def test_catalogs_follow_the_environment(make_dashboard, monkeypatch):
    from portal import settings
    monkeypatch.setitem(settings.CATALOGS, "main_prod", {"dev": "main_dev", "test": "main_test"})
    d = make_dashboard("swap", "title: Swap\ndatasets:\n  x: {sql: sql/x.sql}\n",
                       {"x": "SELECT * FROM main_prod.sales.orders o JOIN samples.tpch.orders s ON o.id = s.o_orderkey"})
    sql = {env: load_dashboard(d, env=env).datasets["x"].sql for env in ("dev", "test", "prod")}
    assert "main_dev.sales.orders" in sql["dev"] and "main_prod." not in sql["dev"]
    assert "main_test.sales.orders" in sql["test"]
    assert "main_prod.sales.orders" in sql["prod"]
    assert all("samples.tpch.orders" in x for x in sql.values())  # same name everywhere: never swapped


STORE_VISITS = """title: Store Visits
params:
  region: {type: STRING, default: North}
  date_from: {type: DATE, default: '@week_start'}
  date_to: {type: DATE, default: '@week_end'}
datasets:
  points:
    sql: sql/points.sql
    cache: shared
    warm: [{region: North}, {region: South}]
"""
POINTS_SQL = ("SELECT o_orderkey, o_orderdate FROM samples.tpch.orders "
              "WHERE o_orderpriority = :region AND o_orderdate BETWEEN :date_from AND :date_to")


def test_shared_cache_serves_every_viewer_from_one_query(make_dashboard, monkeypatch):
    from portal import data
    from portal.settings import resolve_default

    board = load_dashboard(make_dashboard("store-visits", STORE_VISITS, {"points": POINTS_SQL}))
    assert board.errors == []
    points, calls = board.datasets["points"], []
    monkeypatch.setattr(data, "run_sql", lambda client, sql, params, **kw: calls.append(params) or
                        {"columns": ["n"], "rows": [["1"]], "cut": False})
    monkeypatch.setattr(data, "_cache", {})
    assert points.shared and points.warm
    first = data.fetch(board, points, None, "shared", {"region": "East"})
    second = data.fetch(board, points, None, "shared", {"region": "East"})
    assert (first["cached"], second["cached"], len(calls)) == (False, True, 1)
    bound = {p.name: p.value for p in calls[0]}
    assert bound["date_from"] == resolve_default("@week_start") and bound["date_to"] == resolve_default("@week_end")
    data.fetch(board, points, None, "shared", {"region": "West"})
    assert len(calls) == 2


def test_rejects_warm_without_shared_cache_and_bad_date_defaults(tmp_path):
    d = tmp_path / "bad3"
    (d / "sql").mkdir(parents=True)
    manifest = ["title: Bad", "params:", "  day: {type: STRING, default: '@today'}", "  branch: {type: STRING}", "datasets:",
                "  x: {sql: sql/x.sql, warm: [{region: North}]}"]
    (d / "dashboard.yml").write_text(chr(10).join(manifest))
    (d / "sql" / "x.sql").write_text("SELECT 1 AS n FROM samples.tpch.orders WHERE :branch IS NULL OR :day IS NULL")
    (d / "index.html").write_text("<script>dash.data('x')</script>")
    errs = " ".join(load_dashboard(d).errors)
    assert "warm needs cache: shared" in errs
    assert "['region']" in errs
    assert "on a DATE parameter" in errs


def test_app_code_compiles_on_this_python():
    """The pipeline runs this on Python 3.11, the version Databricks Apps uses, so newer-only syntax fails here first."""
    import py_compile

    root = Path(__file__).resolve().parent.parent
    for path in [*root.glob("src/**/*.py"), *root.glob("scripts/*.py")]:
        py_compile.compile(str(path), doraise=True)


def test_usage_rows_are_batched_with_bound_values(monkeypatch):
    from portal import usage

    class Status:
        state = usage.StatementState.SUCCEEDED
        error = None

    class Client:
        class statement_execution:  # noqa: N801
            calls = []

            @classmethod
            def execute_statement(cls, **kw):
                cls.calls.append(kw)
                return type("R", (), {"status": Status, "statement_id": "x"})

    monkeypatch.setattr(usage, "USAGE_TABLES", {"prod": "main.governance.lakeboard_usage"})
    usage._insert(Client, "wh", "main.governance.lakeboard_usage",
                  [("2026-11-10 01:00:00", "view", "prod", "city-trips", "someone@example.com"), ("2026-11-10 01:00:05", "home", "prod", None, "o'neill@example.com")])
    call = Client.statement_execution.calls[0]
    assert call["statement"].startswith("INSERT INTO IDENTIFIER(:usage_table)")
    assert call["statement"].count("(:event_time") == 2
    assert "main.governance.lakeboard_usage" not in call["statement"] and "o'neill" not in call["statement"]
    params = {p.name: p for p in call["parameters"]}
    assert len(params) == 11
    assert (params["usage_table"].type, params["usage_table"].value) == ("STRING", "main.governance.lakeboard_usage")
    assert params["user_email1"].value == "o'neill@example.com" and params["dashboard1"].value is None
    with pytest.raises(ValueError):
        usage._insert(Client, "wh", "main.governance.lakeboard_usage\n", [])
    assert len(Client.statement_execution.calls) == 1
    assert usage.table_for("prod") == "main.governance.lakeboard_usage" and usage.table_for("dev") is None
    monkeypatch.setattr(usage, "USAGE_TABLES", {"prod": "not a table"})
    with pytest.raises(ValueError):
        usage.table_for("prod")


def test_xlsx_export_keeps_text_as_text_and_formats_for_printing():
    import io

    from openpyxl import load_workbook

    from portal import xlsx

    content = xlsx.build([{
        "name": "T1-Monday/run", "landscape": True,
        "columns": [{"key": "stop", "label": "Stop", "width": 6}, {"key": "note", "label": "Comments", "width": 40},
                    {"key": "map", "label": "Google Maps", "link": True}],
        "rows": [{"stop": 1, "note": "=HYPERLINK(1)", "map": "https://www.google.com/maps?q=1,2"}, {"stop": 2, "note": None, "map": "javascript:alert(1)"}],
    }])
    ws = load_workbook(io.BytesIO(content)).active
    assert ws.title == "T1-Monday run"
    assert [c.value for c in ws[1]] == ["Stop", "Comments", "Google Maps"] and ws["A1"].font.bold
    assert ws["A2"].value == 1 and ws["B2"].data_type == "s" and ws["B2"].value == "=HYPERLINK(1)"
    assert ws["C2"].hyperlink.target.startswith("https://www.google.com/") and ws["C3"].hyperlink is None
    assert ws.freeze_panes == "A2" and ws.page_setup.orientation == "landscape" and ws.column_dimensions["B"].width == 40
    assert xlsx.safe_filename("runsheet_T1-Monday") == "runsheet_T1-Monday.xlsx" and "/" not in xlsx.safe_filename("../../x")
    with pytest.raises(xlsx.XlsxError):
        xlsx.build([])


# --- /api/xlsx and /api/health (no Databricks needed: the signed-in check is stubbed) ---

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import app as portal_app
    monkeypatch.setattr(portal_app, "current_user", lambda request: object())
    return TestClient(portal_app.app)


@pytest.mark.parametrize("payload", [
    {"sheets": [{"columns": 5, "rows": []}]},
    {"sheets": [{"columns": [{"key": "a"}], "rows": 5}]},
    {"sheets": [{"columns": [{"key": ["a"]}], "rows": [{"a": 1}]}]},
    {"sheets": [{"columns": [{"key": "a"}], "rows": [5]}]},
    {"sheets": [5]},
    {"sheets": "x"},
    [1, 2],
])
def test_xlsx_rejects_malformed_payloads_with_400(client, payload):
    res = client.post("/api/xlsx", json=payload)
    assert res.status_code == 400
    assert res.json()["detail"]


def test_xlsx_rejects_non_json_with_400(client):
    assert client.post("/api/xlsx", content=b"not json").status_code == 400


def test_xlsx_valid_payload_builds_a_workbook(client):
    from io import BytesIO
    from openpyxl import load_workbook
    payload = {"name": "Orders", "sheets": [{"name": "Stops", "columns": [{"key": "a", "label": "A", "link": True}],
               "rows": [{"a": "=1+1"}, {"a": "https://example.com/x"}, {"a": "javascript:alert(1)"}]}]}
    res = client.post("/api/xlsx", json=payload)
    assert res.status_code == 200
    ws = load_workbook(BytesIO(res.content))["Stops"]
    assert ws["A2"].value == "=1+1" and ws["A2"].data_type == "s"
    assert ws["A3"].hyperlink is not None
    assert ws["A4"].hyperlink is None


@pytest.mark.parametrize("path", ["/api/health", "/healthz"])
def test_health_endpoints(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert res.json()["ok"] is True

# --- Ask Genie: manifest rules ---

SPACE = "01f154d08a811926afe043c48276059f"
CONV = "01f1aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MSG = "01f1bbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def write_board(tmp_path, genie_yaml, auth=None, name="g"):
    d = tmp_path / name
    (d / "sql").mkdir(parents=True)
    lines = ["title: G", "datasets:", "  x:", "    sql: sql/x.sql"] + ([f"    auth: {auth}"] if auth else []) + genie_yaml
    (d / "dashboard.yml").write_text(chr(10).join(lines))
    (d / "sql" / "x.sql").write_text("SELECT 1 AS n FROM samples.tpch.orders")
    (d / "index.html").write_text("<script>dash.data('x')</script>")
    return load_dashboard(d, env="prod")


# A dashboard with Ask Genie in prod only, open to the `analysts` group; and one without Genie.
SALES = f"""title: Sales Overview
groups: [analysts]
datasets:
  revenue: {{sql: sql/revenue.sql}}
genie:
  space_id: {{prod: '{SPACE}'}}
  sample_questions: ['What was revenue last month?', 'Which region grew fastest?', 'Top 5 customers by revenue?']
  about: Revenue is in US dollars, excluding tax.
"""
REVENUE_SQL = "SELECT date_trunc('month', o_orderdate) AS month, sum(o_totalprice) AS revenue FROM samples.tpch.orders GROUP BY 1"


def boards(root):
    """The two dashboards the route tests serve, keyed by slug."""
    from conftest import write_dashboard
    sales = load_dashboard(write_dashboard(root, "sales-overview", SALES, {"revenue": REVENUE_SQL}), env="prod")
    visits = load_dashboard(write_dashboard(root, "store-visits", STORE_VISITS, {"points": POINTS_SQL}), env="prod")
    assert sales.errors == [] and visits.errors == []
    return {b.slug: b for b in (sales, visits)}


def test_genie_space_per_environment(tmp_path):
    d = boards(tmp_path)["sales-overview"]
    assert d.genie_space("prod") == SPACE and d.genie_space("dev") is None and d.genie_space("test") is None
    assert len(d.genie.sample_questions) == 3 and "US dollars" in d.genie.about
    assert boards(tmp_path / "again")["store-visits"].genie is None


def test_genie_block_accepts_a_good_manifest(tmp_path):
    d = write_board(tmp_path, ["genie:", f"  space_id: {{prod: '{SPACE}', dev: ''}}", "  sample_questions: ['What is revenue?']",
                               "  about: Revenue by month."])
    assert d.errors == []
    assert d.genie_space("prod") == SPACE and d.genie_space("dev") is None
    assert d.genie.sample_questions == ["What is revenue?"] and d.genie.about == "Revenue by month."


@pytest.mark.parametrize("block, expected", [
    (["genie: yes"], "must be a block"),
    (["genie:", f"  space_id: '{SPACE}'"], "per environment"),
    (["genie:", "  space_id: {prod: '01F154D08A811926AFE043C48276059F'}"], "32 lowercase hex"),
    (["genie:", "  space_id: {prod: '../../api/2.0/x'}"], "32 lowercase hex"),
    (["genie:", f"  space_id: {{uat: '{SPACE}'}}"], "'uat' must be one of"),
    (["genie:", f"  space_id: {{prod: '{SPACE}'}}", "  sample_questions: [a, b, c, d, e, f]"], "at most 5"),
    (["genie:", f"  space_id: {{prod: '{SPACE}'}}", "  sample_questions: [[nested]]"], "list of questions"),
    (["genie:", f"  space_id: {{prod: '{SPACE}'}}", "  about: " + "x" * 700], "about must be under"),
    (["genie:", f"  space_id: {{prod: '{SPACE}'}}", "  spaceid: typo"], "unknown setting 'spaceid'"),
])
def test_genie_block_rejects_bad_manifests(tmp_path, block, expected):
    d = write_board(tmp_path, block)
    assert d.genie is None
    assert expected in " ".join(d.errors)


def test_genie_is_refused_on_dashboards_read_as_the_app(tmp_path):
    d = write_board(tmp_path, ["genie:", f"  space_id: {{prod: '{SPACE}'}}"], auth="app")
    assert any("auth: app" in e for e in d.errors) and d.genie is None


# --- Ask Genie: the context preamble ---

def test_context_is_capped_and_plain_text():
    from portal import genie
    raw = {f"k{i}": f"v{i}" for i in range(30)}
    assert len(genie.clean_context(raw)) == genie.MAX_CONTEXT_ITEMS
    out = genie.clean_context({"Bad\nkey": "line1\r\nline2\x00 end", "Long": "y" * 500, "Nested": {"a": 1}, "Flag": True,
                               "Num": 12.5, "": "x", "K" * 60: "v"})
    assert out["Bad key"] == "line1 line2 end"
    assert len(out["Long"]) == genie.MAX_VALUE and out["Num"] == "12.5"
    assert "Nested" not in out and "Flag" not in out and "" not in out and "K" * genie.MAX_KEY in out
    assert genie.clean_context(["not", "a", "dict"]) == {}
    assert genie.clean_question("  What is\x00 revenue?\r\n\r\nby site ") == "What is revenue?\nby site"


def test_preamble_only_uses_declared_params_and_marks_the_question(tmp_path):
    from portal import genie
    both = boards(tmp_path)
    board = both["store-visits"]  # declares region, date_from, date_to
    params = genie.clean_params(board, {"region": "North\nEast", "evil": "x", "date_from": None})
    assert params == {"region": "North East"}
    block = genie.context_block(board, params, {"Channel": "Online"})
    assert "Dashboard: Store Visits." in block and "region = North East" in block and "evil" not in block
    assert "Current view of the dashboard: Channel = Online." in block
    assert "Apply these as filters unless the question says otherwise." in block
    text = genie.message_text(block, "How many visits?")
    assert text.startswith("[Context from the dashboard") and text.endswith("\n\nQuestion: How many visits?")
    assert genie.message_text(None, "How many visits?") == "How many visits?"
    sales = both["sales-overview"]
    assert genie.clean_params(sales, {"end": "2026-10"}) == {}  # filters in the browser only: no SQL params
    assert "US dollars" in genie.context_block(sales, {}, {})


def test_context_is_resent_only_when_it_changes():
    from portal import genie
    sent = genie.SentContext(size=2)
    assert sent.changed("u1", CONV, "A")
    sent.remember("u1", CONV, "A")
    assert not sent.changed("u1", CONV, "A") and sent.changed("u1", CONV, "B") and sent.changed("u2", CONV, "A")
    sent.remember("u1", "c2", "A")
    sent.remember("u1", "c3", "A")
    assert sent.changed("u1", CONV, "A")  # oldest dropped once full


# --- Ask Genie: routes, with a stubbed Genie client (no Databricks needed) ---

class FakeGenie:
    """Stands in for WorkspaceClient().genie. `fail` maps a method name to an exception to raise."""

    def __init__(self):
        from databricks.sdk.service import dashboards as dsh, sql
        self.dsh, self.sql = dsh, sql
        self.calls, self.fail, self.status = [], {}, "COMPLETED"

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def start_conversation(self, space_id, content):
        self._maybe_fail("start_conversation")
        self.calls.append(("start", space_id, content))
        return type("W", (), {"response": self.dsh.GenieStartConversationResponse(conversation_id=CONV, message_id=MSG)})

    def create_message(self, space_id, conversation_id, content):
        self._maybe_fail("create_message")
        self.calls.append(("create", space_id, conversation_id, content))
        msg = self.dsh.GenieMessage(space_id=space_id, conversation_id=conversation_id, content=content, message_id=MSG)
        return type("W", (), {"response": msg})

    def get_message(self, space_id, conversation_id, message_id):
        self._maybe_fail("get_message")
        d = self.dsh
        attachments = [
            d.GenieAttachment(attachment_id="att1", query=d.GenieQueryAttachment(query="SELECT 1", description="Revenue by site")),
            d.GenieAttachment(text=d.TextAttachment(content="Revenue was <b>$1m</b>.")),
            d.GenieAttachment(suggested_questions=d.GenieSuggestedQuestionsAttachment(questions=["By month?", "By\nsite?"])),
        ]
        error = d.MessageError(error="[INSUFFICIENT_PERMISSIONS] no SELECT") if self.status == "FAILED" else None
        return d.GenieMessage(space_id=space_id, conversation_id=conversation_id, content="q", message_id=message_id,
                              status=d.MessageStatus(self.status), attachments=attachments if self.status == "COMPLETED" else [],
                              error=error)

    def get_message_attachment_query_result(self, space_id, conversation_id, message_id, attachment_id):
        self.calls.append(("rows", attachment_id))
        s = self.sql
        cols = [s.ColumnInfo(name="site"), s.ColumnInfo(name="revenue"), s.ColumnInfo(name="note")]
        rows = [[f"site{i}", str(i), None] for i in range(250)]
        st = s.StatementResponse(manifest=s.ResultManifest(schema=s.ResultSchema(columns=cols), total_row_count=250),
                                 result=s.ResultData(data_array=rows))
        return self.dsh.GenieGetMessageQueryResultResponse(statement_response=st)

    def send_message_feedback(self, space_id, conversation_id, message_id, rating):
        self._maybe_fail("send_message_feedback")
        self.calls.append(("feedback", message_id, rating))


@pytest.fixture()
def genie_api(monkeypatch, tmp_path):
    """A signed-in analyst (so Sales Overview opens) whose Genie calls go to FakeGenie. Returns (TestClient, fake)."""
    from fastapi.testclient import TestClient
    import app as portal_app
    from portal import genie as genie_mod
    from portal.auth import User

    fake = FakeGenie()
    user = User(key="u1", email="someone@example.com", groups=frozenset({"analysts"}), client=None)
    monkeypatch.setattr(portal_app, "LIVE", boards(tmp_path))
    monkeypatch.setattr(portal_app, "current_user", lambda request: user)
    monkeypatch.setattr(portal_app, "genie_client", lambda u: type("C", (), {"genie": fake}))
    monkeypatch.setattr(portal_app, "ENV", "prod")
    monkeypatch.setattr(genie_mod, "SENT", genie_mod.SentContext())
    fake.recorded = []
    monkeypatch.setattr(portal_app.usage, "record", lambda *a: fake.recorded.append(a))
    return TestClient(portal_app.app), fake


def test_genie_ask_poll_and_rows(genie_api):
    client, fake = genie_api
    view = {"Period": "YTD Oct 2026", "Region": "North"}
    res = client.post("/api/d/sales-overview/genie/ask", json={"question": "What is revenue?", "context": view, "params": {"end": "2026-10"}})
    assert res.status_code == 200
    assert res.json() == {"conversation_id": CONV, "message_id": MSG, "context_sent": True}
    kind, space, content = fake.calls[0]
    assert (kind, space) == ("start", SPACE)
    assert "Period = YTD Oct 2026; Region = North" in content and content.endswith("Question: What is revenue?")
    assert "end = " not in content  # not a declared parameter
    assert fake.recorded == [("genie_ask", "prod", "someone@example.com", "sales-overview")]  # no question text in usage

    # same view: the follow-up goes as the bare question; a changed view sends the context again
    res = client.post("/api/d/sales-overview/genie/ask", json={"question": "And by site?", "conversation_id": CONV, "context": view})
    assert res.json()["context_sent"] is False and fake.calls[-1] == ("create", SPACE, CONV, "And by site?")
    res = client.post("/api/d/sales-overview/genie/ask", json={"question": "And now?", "conversation_id": CONV, "context": {"Period": "Month, Oct 2026"}})
    assert res.json()["context_sent"] is True and "Period = Month, Oct 2026" in fake.calls[-1][3]

    res = client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}")
    body = res.json()
    assert res.status_code == 200 and body["status"] == "COMPLETED"
    assert body["sql"] == "SELECT 1" and body["description"] == "Revenue by site" and body["text"] == "Revenue was <b>$1m</b>."
    assert body["suggested_questions"] == ["By month?", "By site?"]
    assert body["columns"] == ["site", "revenue", "note"] and len(body["rows"]) == 200 and body["truncated"] is True
    assert body["rows"][1] == ["site1", "1", None]


def test_genie_poll_while_working_and_failed(genie_api):
    client, fake = genie_api
    fake.status = "EXECUTING_QUERY"
    body = client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}").json()
    assert body["status"] == "EXECUTING_QUERY" and body["rows"] == [] and not any(c[0] == "rows" for c in fake.calls)
    fake.status = "FAILED"
    res = client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}")
    assert res.status_code == 200 and res.json()["status"] == "FAILED"
    assert res.json()["error"].startswith("Genie couldn't answer that.") and "INSUFFICIENT_PERMISSIONS" in res.json()["error"]


def test_genie_needs_a_space_in_this_environment(genie_api, monkeypatch):
    client, fake = genie_api
    import app as portal_app
    assert client.post("/api/d/store-visits/genie/ask", json={"question": "Hi"}).status_code == 404  # no genie block
    monkeypatch.setattr(portal_app, "ENV", "dev")
    assert client.post("/api/d/sales-overview/genie/ask", json={"question": "Hi"}).status_code == 404  # prod-only space
    assert client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}").status_code == 404
    assert fake.calls == []


def test_genie_page_config_only_where_a_space_exists(genie_api, monkeypatch):
    client, _ = genie_api
    import app as portal_app
    page = client.get("/d/sales-overview").text
    assert '"genie": {"samples":' in page and "/static/genie.js" in page and SPACE not in page
    assert "/static/genie.js" not in client.get("/d/store-visits").text
    monkeypatch.setattr(portal_app, "ENV", "dev")
    assert "/static/genie.js" not in client.get("/d/sales-overview").text


def test_genie_refuses_people_outside_the_dashboard_groups(genie_api, monkeypatch):
    client, fake = genie_api
    import app as portal_app
    from portal.auth import User
    outsider = User(key="u2", email="other@example.com", groups=frozenset({"viewers"}), client=None)
    monkeypatch.setattr(portal_app, "current_user", lambda request: outsider)
    assert client.post("/api/d/sales-overview/genie/ask", json={"question": "Hi"}).status_code == 403
    assert client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}").status_code == 403
    assert client.post(f"/api/d/sales-overview/genie/{CONV}/{MSG}/feedback", json={"rating": "up"}).status_code == 403
    assert fake.calls == []


@pytest.mark.parametrize("path", [
    f"/api/d/sales-overview/genie/{CONV}/not-an-id",
    f"/api/d/sales-overview/genie/{CONV.upper()}/{MSG}",
    f"/api/d/sales-overview/genie/{CONV}x/{MSG}",
])
def test_genie_rejects_bad_ids(genie_api, path):
    client, fake = genie_api
    assert client.get(path).status_code == 400
    assert fake.calls == []


@pytest.mark.parametrize("body", [
    {"question": ""},
    {"question": "   "},
    {"question": 5},
    {"question": "x" * 1001},
    {"question": "Hi", "conversation_id": "../../x"},
    {"question": "Hi", "conversation_id": 7},
    ["not", "an", "object"],
])
def test_genie_ask_validates_its_input(genie_api, body):
    client, fake = genie_api
    assert client.post("/api/d/sales-overview/genie/ask", json=body).status_code == 400
    assert client.post("/api/d/sales-overview/genie/ask", content=b"not json").status_code == 400
    assert fake.calls == []


def test_genie_side_failures_become_plain_messages(genie_api):
    from databricks.sdk.errors import InternalError, NotFound, PermissionDenied, TooManyRequests
    client, fake = genie_api
    cases = [
        (PermissionDenied("You need CAN RUN"), 403, "Ask the data team for access"),
        (PermissionDenied("Provided OAuth token does not have required scopes: genie"), 403, "accept the prompt"),
        (TooManyRequests("slow down"), 429, "Genie is busy. Try again in a minute."),
        (TimeoutError("Timed out after 0:00:15"), 503, "isn't answering"),
        (NotFound("no such conversation"), 404, "Start a new chat"),
        (InternalError("boom"), 503, "isn't answering"),
        (ConnectionError("reset"), 503, "isn't answering"),
    ]
    for exc, code, words in cases:
        fake.fail = {"start_conversation": exc, "get_message": exc}
        res = client.post("/api/d/sales-overview/genie/ask", json={"question": "Hi"})
        assert res.status_code == code and words in res.json()["error"], exc
        res = client.get(f"/api/d/sales-overview/genie/{CONV}/{MSG}")
        assert res.status_code == code and words in res.json()["error"], exc
    busy = TimeoutError("Timed out")
    busy.__cause__ = TooManyRequests("429")
    fake.fail = {"start_conversation": busy}
    assert client.post("/api/d/sales-overview/genie/ask", json={"question": "Hi"}).status_code == 429
    assert fake.recorded == []  # nothing recorded for questions that never reached Genie


def test_genie_feedback(genie_api):
    from databricks.sdk.errors import TooManyRequests
    client, fake = genie_api
    res = client.post(f"/api/d/sales-overview/genie/{CONV}/{MSG}/feedback", json={"rating": "up"})
    assert res.status_code == 200 and fake.calls[-1] == ("feedback", MSG, fake.dsh.GenieFeedbackRating.POSITIVE)
    client.post(f"/api/d/sales-overview/genie/{CONV}/{MSG}/feedback", json={"rating": "down"})
    assert fake.calls[-1][2] == fake.dsh.GenieFeedbackRating.NEGATIVE
    assert client.post(f"/api/d/sales-overview/genie/{CONV}/{MSG}/feedback", json={"rating": "meh"}).status_code == 400
    assert client.post(f"/api/d/sales-overview/genie/{CONV}/bad/feedback", json={"rating": "up"}).status_code == 400
    fake.fail = {"send_message_feedback": TooManyRequests("slow")}
    assert client.post(f"/api/d/sales-overview/genie/{CONV}/{MSG}/feedback", json={"rating": "up"}).status_code == 429


def test_genie_client_keeps_the_viewers_identity(monkeypatch):
    from portal import genie

    class Cfg:
        retry_timeout_seconds = 300
        token = "the-viewers-token"

        def copy(self):
            c = Cfg()
            c.token = self.token
            return c

    made = []
    monkeypatch.setattr(genie, "WorkspaceClient", lambda config: made.append(config) or "client")
    viewer = type("U", (), {"config": Cfg()})
    assert genie.client_for(viewer) == "client"
    assert made[0].token == "the-viewers-token" and made[0].retry_timeout_seconds == genie.RETRY_SECONDS
    assert viewer.config.retry_timeout_seconds == 300  # the viewer's own client is unchanged


def test_shell_shows_the_configured_brand(monkeypatch):
    from fastapi.testclient import TestClient
    import app as portal_app
    from portal.auth import User
    user = User(key="u", email="someone@example.com", groups=frozenset(), client=None)
    monkeypatch.setattr(portal_app, "current_user", lambda request: user)
    monkeypatch.setattr(portal_app.usage, "record", lambda *a: None)
    monkeypatch.setitem(portal_app.BRAND, "name", "Acme <Insights>")
    monkeypatch.setitem(portal_app.BRAND, "logo", "/static/brand/acme.svg")
    page = TestClient(portal_app.app).get("/").text
    assert "<title>Dashboards · Acme &lt;Insights&gt;</title>" in page
    assert 'src="/static/brand/acme.svg"' in page and "[[" not in page
    assert '"tz": "' in page and '"locale": "' in page


def test_local_hosts_override_the_committed_ones(tmp_path):
    from portal import settings
    cfg = {"environments": {"dev": {"host": "adb-0.0.azuredatabricks.net"}, "prod": {"host": "adb-2.2.azuredatabricks.net"}}}
    missing = tmp_path / "environments.local.yml"
    assert settings.with_local_hosts(cfg, missing)["environments"]["dev"]["host"] == "adb-0.0.azuredatabricks.net"
    missing.write_text("environments:\n  dev: {host: DBC-1.cloud.databricks.com}\n")
    out = settings.with_local_hosts(cfg, missing)["environments"]
    assert out == {"dev": {"host": "dbc-1.cloud.databricks.com"}, "prod": {"host": "adb-2.2.azuredatabricks.net"}}
    missing.write_text("environments:\n  staging: {host: x}\n")
    with pytest.raises(ValueError, match="staging"):
        settings.with_local_hosts(cfg, missing)


# ---------- navigation sub-menus (`group:`, decision 0017) ----------

NAV_SQL = {"x": "SELECT 1 AS n FROM samples.tpch.region"}


def nav_board(make_dashboard, slug, order, group_line=""):
    manifest = f"title: {slug.upper()}\nsection: Samples\norder: {order}\n{group_line}\ndatasets:\n  x: {{sql: sql/x.sql}}\n"
    return load_dashboard(make_dashboard(slug, manifest, NAV_SQL), env="prod")


def test_group_is_optional_short_text(make_dashboard):
    assert nav_board(make_dashboard, "plain", 1).group == ""
    ok = nav_board(make_dashboard, "ok", 1, "group: Trip Reports")
    assert ok.errors == [] and ok.group == "Trip Reports"
    for bad in ("group: " + "x" * 41, "group: [a, b]", "group: ' padded '"):
        board = nav_board(make_dashboard, f"bad{len(bad)}", 1, bad)
        assert any("group must be" in e for e in board.errors), bad
        assert board.group == ""


def test_nav_puts_a_group_where_its_first_dashboard_would_be(make_dashboard, monkeypatch):
    import app as portal_app
    from portal.auth import User

    boards = [nav_board(make_dashboard, "a", 1), nav_board(make_dashboard, "b", 2, "group: Trips"),
              nav_board(make_dashboard, "c", 3), nav_board(make_dashboard, "d", 4, "group: Trips")]
    monkeypatch.setattr(portal_app, "LIVE", {b.slug: b for b in boards})
    html = portal_app.nav_html(User(key="u", email="u@example.com", groups=frozenset(), client=None), "d")
    assert html.count('class="pn-group"') == 1 and html.count("<summary>Trips</summary>") == 1
    assert "<details open>" in html  # expanded by default
    order = [html.index(f'href="/d/{s}"') for s in "abcd"]
    assert order[0] < html.index("<summary>") < order[1] < order[3] < order[2]  # b and d grouped, before c
    group = html[html.index('class="pn-group"'):html.index("</details>")]
    assert '/d/b"' in group and '/d/d" aria-current="page"' in group and "/d/c" not in group
