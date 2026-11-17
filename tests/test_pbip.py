"""scripts/pbip_summary.py against the synthetic Power BI Project in tests/fixtures/pbip (no Databricks, no Power BI)."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pbip_summary as ps  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "pbip"


@pytest.fixture(scope="module")
def tmdl():
    return ps.summarise(FIX / "TpchSales.pbip")


@pytest.fixture(scope="module")
def legacy():
    return ps.summarise(FIX / "legacy")


def table(s, name):
    return next(t for t in s["model"]["tables"] if t["name"] == name)


def measure(s, name):
    return next(m for t in s["model"]["tables"] for m in t["measures"] if m["name"] == name)


def page(s, name):
    return next(p for p in s["report"]["pages"] if p["display_name"] == name)


# --- finding the parts ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("arg", ["TpchSales.pbip", "TpchSales.Report", "TpchSales.SemanticModel", "."])
def test_locates_report_and_model_from_any_entry_point(arg):
    s = ps.summarise(FIX / arg)
    assert s["model"]["format"] == "TMDL"
    if arg != "TpchSales.SemanticModel":
        assert s["report"]["format"] == "PBIR"
        assert Path(s["model_folder"]).name == "TpchSales.SemanticModel"


def test_fixture_is_marked_synthetic():
    assert "SYNTHETIC" in (FIX / "README.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" in (FIX / "TpchSales.SemanticModel" / "definition" / "model.tmdl").read_text(encoding="utf-8")
    assert "SYNTHETIC" in (FIX / "legacy" / "TpchLegacy.SemanticModel" / "model.bim").read_text(encoding="utf-8")


def test_tmdl_fixture_uses_tabs():
    text = (FIX / "TpchSales.SemanticModel" / "definition" / "tables" / "orders.tmdl").read_text(encoding="utf-8")
    assert "\n\tmeasure Revenue" in text


# --- TMDL model -------------------------------------------------------------------------------------------------

def test_tmdl_tables_columns_and_hidden_flags(tmdl):
    names = {t["name"] for t in tmdl["model"]["tables"]}
    assert names == {"orders", "lineitem", "customer", "nation", "region", "Date"}
    orders = table(tmdl, "orders")
    cols = {c["name"]: c for c in orders["columns"]}
    assert cols["o_orderkey"]["hidden"] and cols["o_orderkey"]["data_type"] == "int64"
    assert not cols["o_orderdate"]["hidden"] and cols["o_orderdate"]["data_type"] == "dateTime"
    assert cols["Is Urgent"]["calculated"] and "IN {" in cols["Is Urgent"]["expression"]
    assert table(tmdl, "lineitem")["hidden"]


def test_tmdl_databricks_sources_resolve_to_three_part_names(tmdl):
    src = {t["name"]: t["partitions"][0]["source"] for t in tmdl["model"]["tables"]}
    assert src["orders"]["kind"] == "Databricks"
    assert src["orders"]["object"] == "samples.tpch.orders"
    assert src["orders"]["server"] == "example.cloud.databricks.com"  # resolved from the M parameter
    assert src["lineitem"]["object"] == "samples.tpch.lineitem"  # chained navigation on one line
    assert src["customer"]["object"] == "samples.tpch.customer"
    assert "FROM samples.tpch.nation" in src["nation"]["native_sql"]
    assert src["Date"]["kind"].startswith("Calculated table")
    assert table(tmdl, "lineitem")["partitions"][0]["mode"] == "directQuery"


def test_tmdl_parameters(tmdl):
    assert tmdl["model"]["parameters"] == {
        "DatabricksHost": "example.cloud.databricks.com",
        "DatabricksHttpPath": "/sql/1.0/warehouses/0000000000000000",
    }


def test_tmdl_measures_and_flags(tmdl):
    rev = measure(tmdl, "Revenue")
    assert rev["expression"] == "SUM(orders[o_totalprice])" and rev["flags"] == {}
    assert rev["description"] == "Gross order value, as stored in TPC-H."
    ly = measure(tmdl, "Revenue LY")
    assert "SAMEPERIODLASTYEAR('Date'[Date])" in ly["expression"]  # multi-line expression kept whole
    assert ly["flags"]["time intelligence"] == ["SAMEPERIODLASTYEAR"]
    assert "CALCULATE" in ly["flags"]["filter context"]
    assert ly["refs"]["measures"] == ["Revenue"] and "Date[Date]" in ly["refs"]["columns"]
    assert measure(tmdl, "Revenue YoY %")["flags"] == {"non-additive": ["DIVIDE"]}
    assert "DISTINCTCOUNT" in measure(tmdl, "Order Count")["flags"]["non-additive"]
    assert "USERELATIONSHIP" in measure(tmdl, "Shipped Revenue")["flags"]["filter context"]
    assert measure(tmdl, "Revenue")["format"] == "#,##0.00"


def test_tmdl_relationships(tmdl):
    rels = {(r["from_table"], r["from_column"]): r for r in tmdl["model"]["relationships"]}
    assert len(rels) == 6
    r = rels[("orders", "o_custkey")]
    assert (r["to_table"], r["to_column"], r["from_cardinality"], r["to_cardinality"], r["cross_filter"], r["active"]) \
        == ("customer", "c_custkey", "many", "one", "single", True)
    assert rels[("lineitem", "l_orderkey")]["cross_filter"] == "both"
    assert rels[("lineitem", "l_shipdate")]["active"] is False


def test_tmdl_rls(tmdl):
    (role,) = tmdl["model"]["roles"]
    assert role["name"] == "Region Managers" and role["permission"] == "read"
    assert role["filters"] == [{"table": "region", "expression": "'region'[r_name] IN { \"EUROPE\", \"AMERICA\" }",
                                "flags": {}}]


# --- PBIR report ------------------------------------------------------------------------------------------------

def test_pbir_pages_in_order(tmdl):
    assert [p["display_name"] for p in tmdl["report"]["pages"]] == ["Overview", "Customers"]


def test_pbir_visuals_fields_titles_and_slicers(tmdl):
    ov = page(tmdl, "Overview")
    by_type = {v["type"]: v for v in ov["visuals"]}
    card = by_type["card"]
    assert card["title"] == "Revenue"
    assert card["fields"]["Values"][0] == {"kind": "measure", "table": "orders", "name": "Revenue",
                                           "text": "orders.[Revenue]"}
    line = by_type["lineChart"]
    assert [f["text"] for f in line["fields"]["Category"]] == ["Date.Month"]
    assert [f["text"] for f in line["fields"]["Y"]] == ["orders.[Revenue]", "orders.[Revenue LY]"]
    assert line["fields"]["Y"][1]["display_name"] == "Last year"
    slicer = by_type["slicer"]
    assert slicer["slicer"] and slicer["selection"] == "region.r_name in (EUROPE)"
    assert ov["filters"][0]["condition"] == "Date.Year in (1997)"
    assert tmdl["report"]["filters"][0]["condition"] == "not (orders.o_orderstatus in (P))"


def test_pbir_bar_table_and_aggregation(tmdl):
    det = {v["type"]: v for v in page(tmdl, "Customers")["visuals"]}
    assert det["clusteredBarChart"]["fields"]["Category"][0]["text"] == "nation.n_name"
    assert det["clusteredBarChart"]["filters"][0]["type"] == "TopN"
    values = det["tableEx"]["fields"]["Values"]
    assert [v["kind"] for v in values] == ["column", "column", "measure", "measure", "aggregation"]
    assert values[-1]["text"] == "Sum(lineitem.l_quantity)"
    assert det["slicer"]["selection"] is None


# --- TMSL + PBIR-Legacy -----------------------------------------------------------------------------------------

def test_bim_model(legacy):
    m = legacy["model"]
    assert m["format"].startswith("TMSL")
    src = {t["name"]: t["partitions"][0]["source"] for t in m["tables"]}
    assert src["orders"]["kind"] == "Databricks" and src["orders"]["object"] == "samples.tpch.orders"
    assert src["customer"]["kind"] == "Snowflake"
    assert src["customer"]["object"] == "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
    assert src["Targets"]["kind"] == "Excel" and src["Targets"]["location"].startswith("https://example.sharepoint.com")
    assert src["Regions"]["kind"].startswith("SQL Server") and src["Regions"]["object"] == "dbo.Regions"
    assert src["Regions"]["database"] == "Reference"
    ytd = measure(legacy, "Revenue YTD")
    assert ytd["expression"].startswith("TOTALYTD(")  # list-of-lines expression joined and trimmed
    assert ytd["flags"]["time intelligence"] == ["TOTALYTD"]
    order_year = next(c for c in table(legacy, "orders")["columns"] if c["name"] == "Order Year")
    assert order_year["calculated"] and order_year["expression"] == "YEAR(orders[o_orderdate])"
    m2m = next(r for r in m["relationships"] if r["to_table"] == "Targets")
    assert (m2m["from_cardinality"], m2m["to_cardinality"], m2m["cross_filter"]) == ("many", "many", "both")
    assert m["roles"][0]["filters"][0]["expression"] == 'customer[C_MKTSEGMENT] = "BUILDING"'


def test_legacy_report(legacy):
    r = legacy["report"]
    assert r["format"].startswith("PBIR-Legacy")
    assert [p["display_name"] for p in r["pages"]] == ["Summary", "Segments", "Tooltip page"]
    assert r["pages"][2]["hidden"]
    summary = {v["type"]: v for v in r["pages"][0]["visuals"]}
    assert summary["card"]["fields"]["Values"][0]["text"] == "orders.[Revenue]"
    assert summary["lineChart"]["title"] == "Revenue year to date"
    assert summary["slicer"]["selection"] == "customer.C_MKTSEGMENT in (BUILDING, MACHINERY)"
    assert r["pages"][0]["filters"][0]["condition"] == "orders.Order Year >= 1995"
    seg = {v["type"]: v for v in r["pages"][1]["visuals"]}
    assert [f["text"] for f in seg["tableEx"]["fields"]["Values"]] == [
        "customer.C_NAME", "orders.[Revenue]", "Max(orders.o_totalprice)"]


# --- unit pieces ------------------------------------------------------------------------------------------------

def test_dax_flags_ignore_comments_strings_and_names():
    assert ps.dax_flags('SUM(t[x]) // CALCULATE(\n') == {}
    assert ps.dax_flags('"FILTER(" & [All Sales]') == {}
    assert ps.dax_flags("RANKX(ALL(c[n]), [Rev])") == {"filter context": ["ALL"], "ranking / row context": ["RANKX"]}
    assert ps.dax_flags("[a] / [b]") == {"non-additive": ["/"]}
    assert "security" in ps.dax_flags("t[email] = USERPRINCIPALNAME()")


def test_analyse_m_other_connectors():
    m = ps.analyse_m('let S = SharePoint.Files("https://x.sharepoint.com/sites/a", [ApiVersion = 15]) in S')
    assert m["kind"] == "SharePoint" and m["location"] == "https://x.sharepoint.com/sites/a"
    m = ps.analyse_m('let S = Sql.Database("srv", "db", [Query="SELECT 1 AS x"]) in S')
    assert m["native_sql"] == "SELECT 1 AS x" and m["database"] == "db"
    m = ps.analyse_m('Databricks.Query("h", "/p", "SELECT * FROM main.s.t")')
    assert m["kind"] == "Databricks (native SQL)" and m["native_sql"] == "SELECT * FROM main.s.t"
    m = ps.analyse_m('Table.FromRows(Json.Document(Binary.Decompress(Binary.FromText("i45W", BinaryEncoding.Base64), Compression.Deflate)))')
    assert m["kind"].startswith("Entered data")
    assert ps.analyse_m("let S = #\"Base Query\" in S", queries={"Base Query"})["references"] == ["Base Query"]
    assert ps.analyse_m("")["kind"] is None


def test_tmdl_parser_spaces_backticks_and_quoted_names():
    text = (
        "table 'Sales Fact'\n"
        "    measure 'It''s big' = ```\n"
        "            VAR x = 1\n"
        "            RETURN x\n"
        "            ```\n"
        "        formatString: 0\n"
        "    column 'Order Date'\n"
        "        dataType: dateTime\n"
        "        isHidden\n"
    )
    (t,) = ps.parse_tmdl(text)
    assert t["name"] == "Sales Fact"
    m, c = t["children"]
    assert m["name"] == "It's big" and m["value"] == "VAR x = 1\nRETURN x" and m["props"]["formatString"] == "0"
    assert c["name"] == "Order Date" and c["props"]["isHidden"] is True


def test_robust_to_missing_parts(tmp_path):
    shutil.copytree(FIX / "TpchSales.Report", tmp_path / "Only.Report")
    s = ps.summarise(tmp_path / "Only.Report")
    assert s["model"] is None and s["report"]["pages"]
    assert any("semantic model" in w for w in s["warnings"])
    (tmp_path / "Only.Report" / "definition" / "pages" / "detail" / "page.json").write_text("{not json", encoding="utf-8")
    s = ps.summarise(tmp_path / "Only.Report")
    assert [p["display_name"] for p in s["report"]["pages"]] == ["Overview"]
    assert any("could not read JSON" in w for w in s["warnings"])
    empty = tmp_path / "Empty.SemanticModel"
    empty.mkdir()
    assert ps.summarise(empty)["model"] is None


def test_cli_text_and_json(capsys):
    assert ps.main([str(FIX / "TpchSales.pbip")]) == 0
    out = capsys.readouterr().out
    for needle in ("samples.tpch.orders", "TRANSLATE WITH CARE (time intelligence: SAMEPERIODLASTYEAR",
                   "INACTIVE", "role Region Managers", "Page 1: Overview", "SLICER \"Region\""):
        assert needle in out
    assert ps.main([str(FIX / "legacy"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["report"]["format"].startswith("PBIR-Legacy") and data["model"]["roles"]
