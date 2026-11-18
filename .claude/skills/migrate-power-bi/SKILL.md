---
name: migrate-power-bi
description: Move a Power BI report saved as a Power BI Project (PBIP, .pbip / .Report / .SemanticModel folders) into a LakeBoard dashboard and prove its numbers match. Use when asked to migrate, convert or rebuild a Power BI report, PBIP, PBIR, TMDL or model.bim in this repository.
---

# Move a Power BI report into LakeBoard

Read `docs/MIGRATION.md` and `docs/AUTHORING.md` first. Work in order and stop where a step says so.

## 1. Check it is worth moving

- Ask the user which report, which Power BI workspace, and which Databricks CLI profile and SQL warehouse to test
  with. Never pick a profile yourself.
- Usage: if `usage/reports.csv` exists, read it; otherwise ask the user to run
  `python scripts/powerbi_usage.py --days 28 --report "<report name>"` (it needs their `az login`).
- Apply MIGRATION.md "2. Decide: migrate, merge or retire". No views in 28 days, or a big overlap with an existing
  dashboard: say so and ask before building anything.

## 2. Read the report

```
python scripts/pbip_summary.py <path to the .pbip, .Report or .SemanticModel folder>
python scripts/pbip_summary.py <path> --json     # when you need the detail
```

It only reads files. It lists tables and columns, each table's source, measures with their DAX, calculated
columns and tables, relationships, row-level security roles, and every page's visuals, slicers and filters.
Anything marked `TRANSLATE WITH CARE` or `INACTIVE` needs a deliberate decision in step 4. Read its warnings.
If the report connects live to a published model (`byConnection`), ask for that model's project folder too.

## 3. Map every source table to Unity Catalog

- For each table, find the Unity Catalog table or view it should read. A Databricks source already names
  `catalog.schema.table`; confirm it exists and you can read it (use the Databricks data discovery skill, or
  `DESCRIBE TABLE` with the user's profile).
- Other sources (SQL Server, Snowflake, SharePoint, Excel, entered data): find the copy already landed in Unity
  Catalog. If there is none, **stop** and give the user the list of what must be landed first. Don't read the
  old source from the dashboard.
- Never invent tables or columns. If a column the report uses has no match, ask.
- Calculated tables (a DAX calendar, for example) become SQL or an existing UC table. Check whether the calendar
  is fiscal: a year-end such as `TOTALYTD(..., "06-30")` or a fiscal column changes every period comparison.
- Use the prod catalog name, and add it to `catalogs:` in `src/environments.yml` only with the user's agreement
  (that file is platform, not dashboard).

## 4. Translate measures to SQL

- One dataset (`sql/<name>.sql`) per group of visuals that share a grain (tiles, one per chart, one per table).
  Aggregate in SQL to the grain the page shows. Keep each file one read-only `SELECT`/`WITH`.
- Put the original DAX in a comment above the SQL that replaces it:
  ```sql
  -- Power BI measure orders[Revenue LY]:
  --   CALCULATE([Revenue], SAMEPERIODLASTYEAR('Date'[Date]))
  ```
- Watch for, and say in the dashboard README how you handled:
  - **Non-additive measures** (`DIVIDE`, ratios, `DISTINCTCOUNT`, averages): compute numerator and denominator at
    each grain; never sum or average a percentage in the page.
  - **Totals that aren't sums:** a Power BI total re-evaluates the measure over all rows. Return the total from
    SQL (a separate row or dataset), don't add up the rows in JavaScript.
  - **Time intelligence** (`SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, ...): write the date ranges explicitly.
    Confirm calendar vs fiscal year and how partial periods are treated.
  - **Filter context** (`CALCULATE`, `ALL*`, `REMOVEFILTERS`, `KEEPFILTERS`, `USERELATIONSHIP`): work out which
    slicers each measure ignores or overrides, and which relationship (active or inactive) it uses.
  - **Many-to-many or both-direction relationships:** check the join doesn't duplicate rows.
- **Row-level security:** don't rebuild a role in page code. Each role becomes a Unity Catalog row filter on the
  table (ask the data owner; you don't create it), or dashboard / dataset `groups:` in `dashboard.yml`. Queries
  run as the viewer, so UC rules apply to the dashboard automatically. Don't use `cache: shared` or `auth: app`
  on data that has row-level security.

## 5. Map the page

| Power BI | LakeBoard |
|---|---|
| card, multi-row card, KPI | `kit.tiles` |
| line, area chart | `kit.line` |
| bar, column chart | `kit.bars` (ranked); `d3` for stacked or clustered |
| table, matrix | `kit.table` (CSV download included) |
| slicer that changes what SQL reads (date range, period, large lists) | `params:` in `dashboard.yml` + `kit.filters` + `dash.setParams` |
| slicer over a few values already in the result | `kit.filters`, filtering in the browser |
| page and report filters | `WHERE` in the SQL, or `params` defaults |

Keep the page names, order and slicer defaults people know. Fix what is broken instead of copying it. **Ask
before dropping any visual**, and list the dropped ones in the README.

## 6. Build and check

```
python scripts/new_dashboard.py <slug> "<Title>" --owner <Team> --section <Section>
```

Set `replaces:` in `dashboard.yml` to the report's name and workspace. Write `sql/`, `dashboard.yml` and
`index.html` as in AUTHORING.md, staying inside the dashboard folder. Then:

```
python scripts/check.py --static
python -m pytest -q
python scripts/check.py --env dev --profile <profile> --warehouse <id>
```

Run it locally (`./scripts/run_local.ps1 -Profile <p> -Warehouse <id>`), open `/d/<slug>`, fix console errors.

## 7. Reconcile

MIGRATION.md "5. Prove the numbers". For each page, pick 3 to 5 numbers (a headline tile, a chart point, a table
row, a total) and match Power BI to the cent with the same filters, for at least two periods. The user reads the
Power BI values; you run the SQL. Record them in the dashboard's `README.md`:

| Page | Number | Period and filters | Power BI | Dashboard | Note |
|---|---|---|---|---|---|

Explain every difference. Don't call the migration done while a difference is unexplained.

## 8. Pull request

Branch from `main` and open the pull request into `develop` (`docs/PROMOTION.md`). In the description list the
measures marked "translate with care" and how each was handled, any dropped visual, and the reconciliation table.

## Rules

- No business data in the repository: no exported rows, screenshots with figures, or PBIX/`cache.abf` files.
  Reconciliation values in the README are fine once the owner agrees.
- Never invent tables or columns; never create or alter tables, views or row filters yourself.
- Leave GRANTs, deploys and starting or stopping Databricks Apps to a person.
