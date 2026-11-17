---
name: new-dashboard
description: Add a dashboard to LakeBoard, or move a Power BI report into it. Use when asked to create, build or migrate a dashboard or report in this repository.
---

# Add a dashboard to the portal

1. Read `docs/AUTHORING.md` (the contract and the `dash` / `kit` APIs). If the request is to replace a Power BI
   report, also read `docs/MIGRATION.md` and map the report's pages, measures, slicers and source views first.
2. Confirm with the user: the title, the owning team, the section of the left navigation, who may open it, and
   which Databricks CLI profile and SQL warehouse to test with. Never pick a profile yourself.
3. Scaffold: `python scripts/new_dashboard.py <slug> "<Title>" --owner <Team> --section <Section>`.
4. Write the SQL in `sql/`. Check each query on the warehouse with the user's profile before building the page.
   Read-only; tables as `catalog.schema.table` with the prod catalog name (an allowed catalog in
   `src/environments.yml`); filter values as `:name` parameters.
5. Write `index.html` with `kit` components and the theme variables. Use `src/dashboards/city-trips/` as the
   worked example.
6. Run `python scripts/check.py --static` and `python -m pytest -q`, then start the portal locally
   (`./scripts/run_local.sh <profile> <warehouse>` or `./scripts/run_local.ps1 -Profile <p> -Warehouse <id>`) and open
   `http://localhost:8000/d/<slug>`. Fix console errors and check the loading, empty and error states.
7. For a migration, reconcile against Power BI and record the comparison in the dashboard's `README.md`.
8. Branch from `main` and open the pull request into `develop` (`docs/PROMOTION.md`). Don't commit to `main`.
9. Test locally only. Don't start or stop Databricks Apps, run grants or deploy; leave those to a person.
