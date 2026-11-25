# 0001. One app, one folder per dashboard, same SQL everywhere

- **Status:** Accepted

## Context
We are replacing Power BI reports. Some of them use chained DirectQuery and cause capacity spikes. We wanted
dashboards that load their data once, are reviewed in git, and can be built by a data team or by business teams
using an AI coding tool.

## Decision
- One Databricks App hosts every dashboard (`lakeboard` in prod, `lakeboard-test` and `lakeboard-dev`). We do
  not create one app per report.
- A dashboard is one folder under `src/dashboards/<slug>/`: `dashboard.yml` (the manifest), `index.html` (the
  page) and `sql/` (one read-only query per dataset).
- SQL is written with the prod catalog name. When dev and test use other catalogs (for example `main_prod` in prod,
  `main_dev` and `main_test` elsewhere), the app swaps the name at start-up, using `src/environments.yml`. A catalog
  with the same name everywhere, such as `samples`, is left alone.
- `environments:` in `dashboard.yml` switches a dashboard on only in some environments, so unfinished work can be
  merged without appearing in prod.
- Every pull request runs `scripts/check.py --static` and `pytest`. Every deploy also runs each dataset with
  `LIMIT 0` against that environment's catalogs before anything changes.

## Why
- One place to host, one sign-in and permission model, one pipeline.
- An extra dashboard adds no compute of its own. The app's compute is shared.
- The contract in [AUTHORING.md](../AUTHORING.md) is small and checked automatically, so Claude, Codex or a person
  can build a dashboard to it.
- The same SQL can be pasted into the SQL editor and runs unchanged in every environment.

## Limitations
- One app means a shared blast radius. A bad change to the shell, `src/portal/` or the pipeline affects every
  dashboard, and all dashboards share one app's compute.
- At run time, a dashboard that fails validation is left out of the navigation and the others keep working. But the
  pipeline checks fail the whole deploy, so one broken dashboard blocks every dashboard's release.
- No paginated reports, email subscriptions, PDF or PowerPoint export, or data alerts. See
  [MIGRATION.md](../MIGRATION.md) "2. Decide: migrate, merge or retire" and [DESIGN.md](../DESIGN.md) "Known gaps
  against Power BI".
- Pages are code. There is no drag-and-drop editor.

## Alternatives considered
- **Keep Power BI.** Keeps the DirectQuery load and capacity spikes, and the logic stays inside each report.
- **AI/BI (Lakeview) dashboards.** Pages could not use the same `dash` API as Claude Dashboard artifacts or the
  shared page kit, which were goals in [DESIGN.md](../DESIGN.md).
- **One Databricks App per report.** Each app bills while it runs and needs its own permissions and pipeline, and
  the apps share no code.

## Changing it later
A dashboard folder is self-contained, so one could move to its own app by copying the folder and the shared
`src/static/` files. The catalog mapping is in `src/environments.yml`. A change to this decision needs a new record
that supersedes this one.

## Agent-independent authoring

The authoring workflow is now shared across coding agents, with optional adaptation of external prototypes.
See [0012](0012-agent-independent-dashboard-authoring.md). The dashboard folder and hosting runtime stay the same.

## Links

- [DESIGN.md](../DESIGN.md), [AUTHORING.md](../AUTHORING.md), [PROMOTION.md](../PROMOTION.md) "Switching a
  dashboard on per environment"
- `src/portal/settings.py` (`localise_sql`), `src/portal/registry.py`, `scripts/check.py`,
  `.github/workflows/deploy.yml`, `pipelines/deploy-steps.yml`
