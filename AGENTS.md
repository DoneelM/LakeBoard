# Instructions for AI coding tools (Claude Code, Codex, Cursor and others)

LakeBoard: one Databricks App hosting many dashboards under `src/dashboards/`.

## Read what the task needs, not everything

- Adding or changing a dashboard: follow `docs/DASHBOARD_WORKFLOW.md`, the shared workflow for every coding
  agent. `docs/AUTHORING.md` defines the APIs; also read `docs/MIGRATION.md` when replacing a Power BI report.
  Worked example: `src/dashboards/city-trips/`. Business authors can start with `docs/BUSINESS_AUTHORS.md`.
- Changing the platform (`src/app.py`, `src/portal/`, `src/static/`, `scripts/`, the pipelines, `databricks.yml`,
  `resources/`): `docs/DESIGN.md`, `docs/OPERATIONS.md`, and the related record in `docs/decisions/`.
- Caching, refresh, deploys, grants, starting and stopping apps: `docs/OPERATIONS.md`.
- Any branch or pull request: `docs/PROMOTION.md`.
- Before changing behaviour a decision record covers: read that record in `docs/decisions/`.

## Rules

1. **Stay inside one dashboard folder** (`src/dashboards/<slug>/`) for a dashboard change. Platform work follows
   the platform docs above.
2. **SQL is read-only.** One `SELECT`/`WITH` per file, tables written as `catalog.schema.table` with the prod catalog
   name (an allowed catalog in `src/environments.yml`), filter values as `:name` parameters declared in
   `dashboard.yml`. Never create, replace or alter tables or views.
3. **Use `kit` for filters, tiles, tables, charts, maps and CSV.** Don't hand-write another version, and don't
   load anything from another website.
4. **Never put credentials, tokens or people's data in the repository.** `usage/` is ignored for that reason.
5. **Theme, not fixed colours:** use the CSS variables from `src/static/shell.css` (`--brand`, `--accent`,
   `--color-*`, `--chart-1` to `--chart-8`) so pages follow the portal's brand and dark mode. Format numbers and
   dates with `kit.fmt`, which uses the portal's `locale`.
6. **Prove it before you say it is done:**
   ```
   python scripts/check.py --static
   python -m pytest -q
   ```
   Then repeat the tests with another environment, as CI may resolve to one. Bash: `PORTAL_ENV=dev python -m pytest -q`.
   PowerShell: `$env:PORTAL_ENV='dev'; python -m pytest -q; Remove-Item Env:PORTAL_ENV`.
   Finally run it (`./scripts/run_local.sh <profile> <warehouse>` or `./scripts/run_local.ps1`), open the page, and
   confirm it loads with no console errors.
7. **When replacing a Power BI report,** reconcile the numbers and record them in the dashboard's `README.md`.
8. **Branch from `main`; never commit to `main`, `release` or `develop` directly.** Open pull requests in the
   order `develop`, `release`, `main` from the same feature branch, using the PR template.
9. **Record decisions.** A new feature or design decision gets a record in `docs/decisions/` (template in its
   README) in the same pull request, or a new section on the existing record. Don't rewrite history.
10. **Tests must pass in any environment.** Tests must not depend on `PORTAL_ENV` or `DATABRICKS_HOST`; pass
    `env=` explicitly (`load_all(env="prod")`) and build test dashboards in `tmp_path` (`tests/conftest.py`).
11. **Leave live changes to a person.** Don't run GRANTs (`grant_app_access.py --apply`), start or stop Databricks
    Apps, or deploy bundles. Dry runs that only print are fine; always pass an explicit CLI profile the user named.

## Commands

The shared workflow applies whether the author uses repository tools or hands a generated folder to the data
team. Agents that do not discover `AGENTS.md` automatically must be explicitly asked to read it. Agent-specific
skills and instruction files should link to the shared workflow rather than duplicate its steps.

| Task | Command |
|---|---|
| New dashboard | `python scripts/new_dashboard.py <slug> "<Title>" --owner <Team> --section <Section>` |
| Run locally | `./scripts/run_local.sh <cli-profile> <warehouse-id> [dev\|test\|prod]` or `./scripts/run_local.ps1 -Profile <p> -Warehouse <id> [-Env prod]` |
| Static checks | `python scripts/check.py --static; python -m pytest -q` |
| Run every query (LIMIT 0) | `python scripts/check.py --env dev --profile <profile> --warehouse <id>` |
| Show app grants | `python scripts/grant_app_access.py --env <env> --profile <profile> --warehouse <id>` (prints; `--apply` is for a person) |
| Power BI usage | `python scripts/powerbi_usage.py --days 28` |
