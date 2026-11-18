# Synthetic Power BI Project (test fixture)

SYNTHETIC. Hand-written for `tests/test_pbip.py`; not exported from a real report and holds no business data.
It is modelled on the Databricks sample tables `samples.tpch.*` (orders, lineitem, customer, nation, region).
The host names and warehouse ids are placeholders.

| Folder | Formats |
|---|---|
| `TpchSales.pbip`, `TpchSales.Report/`, `TpchSales.SemanticModel/` | PBIR report + TMDL semantic model |
| `legacy/TpchLegacy.Report/`, `legacy/TpchLegacy.SemanticModel/` | PBIR-Legacy `report.json` + TMSL `model.bim` |

Summarise it with `python scripts/pbip_summary.py tests/fixtures/pbip/TpchSales.pbip`.
