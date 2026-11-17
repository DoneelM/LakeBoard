# LakeBoard: design

One Databricks App that hosts many dashboards. Each dashboard is a folder of SQL, one HTML page and a
small manifest, all reviewed and deployed through git. The app's compute is shared, so the cost doesn't grow
with the number of dashboards.

Why each feature and design choice was made, and its limitations, is recorded in [decisions/](decisions/README.md).

## Goals
- **Replace slow Power BI reports.** Reports built on chained DirectQuery models cause capacity spikes and slow
  pages. Here, each page loads its data once and filters in the browser.
- **Feel like a Power BI app.** Dashboards are listed down a left navigation pane, grouped into sections, so
  people find reports where they expect them.
- **Govern data in Unity Catalog, not in each report.** Queries run as the signed-in user (on-behalf-of auth),
  so UC grants, row filters and column masks decide what each person sees.
- **Make adding a dashboard small and safe.** A dashboard is one folder that follows a written contract
  ([AUTHORING.md](AUTHORING.md)) and is checked automatically. The data team hosts and reviews; business teams
  can build, with any AI coding tool.
- **Promote like the rest of the platform.** `develop`, `release` and `main` deploy to dev, test and prod, each
  reading its own catalog if you want ([PROMOTION.md](PROMOTION.md)).
- **Support any coding agent.** Authors follow one shared workflow and target LakeBoard's `dash` and `kit`
  APIs. Direct repository authoring and adapted prototypes produce the same dashboard folder. Business authors
  can use Genie MCP for data discovery and hand the folder to the data team for hosting.

## Non-goals
- Write-back or data entry.
- Pixel-perfect paginated (RDL) output. Paginated reports stay in Power BI or move to scheduled PDF exports.
- A drag-and-drop authoring UI. Pages are code.

## Architecture

```
Browser ──SSO──▶ Databricks App (FastAPI, 1 instance per environment)
                   │  /                       home: dashboards the user may open, by section
                   │  /d/<slug>               shell (left navigation) + the dashboard's index.html
                   │  /api/d/<slug>/data/<id> runs one dataset → JSON rows (cached)
                   │  /api/d/<slug>/sources   when each dataset's source tables last changed (UC metadata)
                   │  /api/d/<slug>/genie/…   Ask Genie: question → Genie space, poll, feedback
                   │  /static/…               dash.js runtime, kit.js page kit, genie.js, d3, Leaflet, theme CSS, logo
                   │
                   ├─ user token (x-forwarded-access-token) ─▶ SQL warehouse ─▶ allowed catalogs
                   ├─ user token ─▶ Genie Conversation API ─▶ the dashboard's Genie space
                   └─ app service principal (auth: app datasets only, e.g. slow federated sources)
```

- **One process, no database.** Manifests and SQL are read from disk at start-up. Query results are held in an
  in-memory TTL cache.
- **Queries use the Databricks SDK Statement Execution API** with named parameters (`:name`). No extra driver
  is needed, and parameters are always bound, never string-formatted.
- **The page receives column names plus rows of strings or nulls,** so pages convert numbers with `kit.num`
  and format them with `kit.fmt`.

## Repository layout

```
databricks.yml                 bundle: variables + dev / test / prod targets
.github/workflows/deploy.yml   GitHub Actions: checks on every PR; deploy on develop (dev), release (test), main (prod)
azure-pipelines.yml            the same for Azure DevOps (pipelines/deploy-steps.yml holds the shared deploy steps)
resources/portal.app.yml       the app resource (warehouse, user scopes: sql, genie, viewers group)
AGENTS.md, CLAUDE.md           shared rules; .claude/skills/new-dashboard links to docs/DASHBOARD_WORKFLOW.md
src/                           ← app source (bundle source_code_path)
  app.yaml                     runtime command + env
  app.py                       FastAPI routes, left navigation, security headers, usage log
  environments.yml             environments, allowed catalogs, sections, brand, locale, libraries, warm times
  portal/                      settings.py, registry.py (manifests + rules), data.py (queries + cache), auth.py,
                               genie.py (Ask Genie), sources.py (freshness), usage.py, xlsx.py
  static/                      dash.js (data runtime), kit.js + kit.css (page kit), genie.js + genie.css,
                               shell.css (theme), vendor/, brand/logo.svg
  templates/shell.html         the page frame: left navigation, title bar
  dashboards/<slug>/           dashboard.yml, index.html, sql/*.sql, README.md
scripts/                       new_dashboard.py, check.py, run_local.ps1 / run_local.sh, grant_app_access.py,
                               build_sources_map.py, powerbi_usage.py
tests/                         pytest: every dashboard valid; the rules reject what they should
docs/                          DESIGN, DASHBOARD_WORKFLOW, BUSINESS_AUTHORS, AUTHORING, PROMOTION, MIGRATION,
                               OPERATIONS, decisions/
```

## Dashboard manifest (`dashboard.yml`)

```yaml
title: Sales and margin
description: Revenue, discount and margin by region and month.
owner: Finance                      # shown on the catalogue card
section: Samples                    # left navigation heading (src/environments.yml)
groups: []                          # workspace groups that see it in the catalogue; [] = everyone with CAN USE
order: 10                           # catalogue sort
datasets:
  monthly:                          # id used by the page: dash.data('monthly')
    title: Revenue and margin by month
    sql: sql/monthly.sql
    cache_ttl: 6h                   # default 1h
  suppliers:
    title: Supplier cost
    sql: sql/suppliers.sql
    cache_ttl: 24h
    auth: app                       # run as the app service principal, cache shared, warm in the background
params:                             # page filters that reach SQL (others stay client-side)
  region: {type: STRING, default: "EUROPE"}
```

The full field list is in [AUTHORING.md](AUTHORING.md). Beyond the example above: `environments` (where it is
switched on), `libs` (extra libraries such as Leaflet), `replaces`, `genie`, and `groups` on a single dataset.

**Rules (checked on every pull request):**
- Every `:name` in a SQL file must be declared under `params`.
- Every `dash.data('<id>')` in `index.html` must be declared under `datasets`.
- SQL must be a single `SELECT` or `WITH` statement. DDL and DML are rejected.
- Every table is `catalog.schema.table`, in a catalog listed in `src/environments.yml`.
- Pages may not load scripts from other sites.
- `section`, `environments` and `libs` must use values from `src/environments.yml`.
- A `genie:` block names a 32-character space id per known environment, and is refused alongside `auth: app` data.

## Environments

| | Dev | Test | Prod |
|---|---|---|---|
| Branch | `develop` | `release` | `main` |
| App | `lakeboard-dev` | `lakeboard-test` | `lakeboard` |
| Catalog (example swap) | `main_dev` | `main_test` | `main_prod` |
| `samples` | `samples` | `samples` | `samples` |

SQL is always written against the prod catalog name. At start-up the app works out its environment from the
workspace host (or `PORTAL_ENV`) and swaps the catalog, using the mapping under `catalogs:` in
`src/environments.yml`. A catalog with the same name everywhere (like `samples`) is listed with `{}` and never
swapped. A non-prod environment shows a badge beside the logo. A dashboard can be limited to some environments
with `environments:`, which is how unfinished work stays out of prod without staying off the branch.

One workspace for all three is fine: give each environment the same host and set `PORTAL_ENV` per app. A single
Databricks Free Edition workspace works for trying it out (serverless starter warehouse, `samples` catalog).

## Navigation and brand

The shell puts a fixed pane on the left, like a Power BI app: the logo and portal name, then each section with
its dashboards in `order`. It lists only what the signed-in person may open. It collapses with the ☰ button
(remembered per browser) and becomes a slide-over on narrow screens. Sections and their order are set in
`src/environments.yml`.

The name and logo come from the `brand:` block in `src/environments.yml` (`name`, `logo`). Pages can show the
same logo with `{{LOGO}}`. `locale:` sets how numbers and dates are written.

## Security model

| Concern | How |
|---|---|
| Who can open the app | App permission `CAN USE`, granted to the `viewers_group` in `databricks.yml` (default `lakeboard-users`, a placeholder), plus any groups you add per target |
| Who sees a dashboard | `groups` in the manifest; the server checks the user's groups on every page and API call |
| What data a user sees | `auth: user` (default): the query runs with the user's token, so UC grants, row filters and masks apply |
| Cache isolation | `auth: user` results are cached **per user**; `auth: app` results are shared, so only use it for data every viewer of that dashboard may see |
| Part of a dashboard | `groups` on a dataset; the server refuses it to anyone else ([OPERATIONS.md](OPERATIONS.md)) |
| What a page can do | A Content-Security-Policy lets the browser load scripts and data only from the portal (plus Google Fonts and OpenStreetMap tiles), so a page can't send data elsewhere |
| What SQL can read | Read-only statements, and only catalogs on the allow-list |
| Runaway queries | Stopped after 10 minutes; results capped at 500,000 rows |
| Ask Genie | Always called with the viewer's token, after the same dashboard `groups` check; not offered on dashboards with `auth: app` data. Questions and answers are shown as text only |
| Secrets | None in the repo. The app SP credentials and user tokens are injected by the platform and never logged |

Row-level security that a Power BI model enforced with roles belongs in Unity Catalog as a row filter on the
views. The portal then enforces it automatically, for every dashboard and for Genie.

## Caching and cost
- **Cache key:** dashboard, dataset, bound parameters, and the user (or `app`). The TTL comes from the manifest.
- **Refresh:** the page's Refresh button sends `?refresh=1` to bypass the cache for that user.
- **Background warming:** `auth: app` datasets are re-run every `cache_ttl`, so slow sources (for example a
  federated table that takes minutes to scan) never block a reader. Shared datasets with a `warm:` list are
  refreshed at the `warm.times` in `src/environments.yml`.
- **Warehouse use:** about one query per dataset per user per TTL. Filtering costs nothing.
- **App use:** one always-on app per environment. Dev and test are stopped after each deploy; prod can be stopped
  out of hours (`databricks apps stop`) if usage allows (decision 0005).

## Freshness label
The title bar tells people how old the data on screen is, so they don't press Refresh for nothing.
- **Oldest fetch time.** The label uses the oldest `fetched_at` of the datasets the page has loaded. A page is only
  as fresh as its stalest part, and reporting the newest would overstate it.
- **Times in the portal's zone.** Times are shown in `warm.timezone` (default UTC) and the `locale:` format.
- **Cache metadata on each dataset response:** `cache` (`user`, `shared`, `warm` or `app`) and `expires_at`
  (`fetched_at` + `cache_ttl`), so the panel can say how the result is shared and how long it is kept.
- **Source change time from metadata, as the app.** `GET /api/d/<slug>/sources` finds the tables in each dataset's
  SQL (the same parsing as `grant_app_access.py`; the catalog is already swapped for the environment), follows views
  through `view_dependencies` (depth 5, 40 tables, cycles skipped) and reports the newest `updated_at` of the managed
  tables underneath. It uses the Unity Catalog Tables API, not SQL, so it costs no warehouse time. It runs as the
  app's service principal because viewers often can't read the tables behind the views they query; it only returns
  times and table names, and only for datasets the viewer may open. The service principal needs `BROWSE` on those
  catalogs, nothing more.
- **View dependencies from a deploy-time map.** BROWSE gives a view's type but not what it reads, so the pipeline
  writes `src/sources_map.json` (`scripts/build_sources_map.py`, run with full metadata) and the app follows views
  through it when it was built for the app's environment. Table times are still read live (decision 0009).
- **Only claim what is known.** Each table gets a `kind`: `managed` (timed), `live` (FOREIGN: read from the remote
  system at query time, so current when fetched), `external` (written outside Unity Catalog, not tracked), `none`
  (a view that reads no table), `static` (a catalog under `static_catalogs`, such as `samples`, whose data never
  changes; never looked up) or `unknown`. Live and external tables are never timed (their `updated_at` doesn't follow writes), but they don't hide
  the managed tables' time either; the dataset is flagged `live` or `partial` and the label says "tracked sources
  unchanged". If any table is `unknown` the dataset's source time is unknown, and the label says nothing rather
  than "source unchanged". Lookups are cached (10 minutes per table, 6 hours per view), run in threads in parallel,
  and the request is cut off after 10 seconds with the rest marked unknown.

## Page runtime (`static/dash.js`) and page kit (`static/kit.js`)
`dash.js` provides LakeBoard's data runtime (originally adapted from the Claude Dashboard `dash` API):
- **Data:** `data(id)` (lazy fetch, then `{status, data, columns, message, refreshing}`) and `onData(fn)`.
- **Filters:** `params()`, `setParams()` and `resetParams()`. Changing a parameter that a dataset's SQL uses re-fetches that dataset.
- **Other:** `allowed(id)`, `env`, `setLink()` (URL hash), `refresh(id)`, `calc()` and `colors`.
- **Load states:** marks get the same `data-dash-source-state` attributes as in artifacts.

`kit.js` holds the shared building blocks: formatting, filter bar, KPI tiles, sortable table with CSV download,
bar and line charts, and a point map. Dashboards use it, which keeps a page to a few hundred lines and makes
every dashboard behave the same.

## Theme
Every colour is a CSS custom property in one block at the top of `src/static/shell.css`, with a dark-mode block
(`prefers-color-scheme: dark`) under it. The default is a neutral slate and indigo. To rebrand, change that block
and the `brand:` logo; nothing else. The block also defines the artifact theme tokens pages use (`--color-fg`,
`--color-panel`, `--cds-chart-*`, …). `dash.colors`, the series palette, is read from `--chart-1` to `--chart-8`
when the page loads.

## Ask Genie
A dashboard with a `genie:` block ([AUTHORING.md](AUTHORING.md)) gets a chat bar at the bottom of the page, like the
one on Databricks AI/BI dashboards. The shell adds it (`static/genie.js`); pages don't build their own.

- **One Genie space per dashboard, per environment.** The manifest names the space id for each environment. No id,
  no bar. Spaces are built and owned by the data team in the workspace; the portal never creates or changes them.
- **Genie Conversation API, as the viewer.** The portal's backend calls `start-conversation`, `messages`,
  `get message`, `query-result` and `feedback` for that space with the viewer's own token (the app's `genie` user
  scope), the same way dataset queries use their token. The browser only ever talks to the portal (the CSP is
  unchanged), and the portal never calls Genie as its service principal. If it did, everyone would see whatever the
  app can read, Unity Catalog row filters would stop applying, and Genie's history would show one user for all.
  For the same reason the bar is refused on dashboards that read data as the app (`auth: app`).
- **Why not Genie One.** Genie One answers across all the data a person can see, without a curated space. A
  dashboard needs answers that use the same views and definitions as its numbers, which is what a curated space
  holds (tables, instructions, example SQL). A general assistant is a separate product decision.
- **How context reaches Genie.** The Conversation API has no field for context. So the portal puts a short
  plain-text preamble before the question: the dashboard title, its `about` text, its SQL parameters, and the page's
  current view from `dash.genieContext()` (many pages filter in the browser, so Genie can't otherwise know the period
  or region on screen). It ends "Apply these as filters unless the question says otherwise", then `Question: …`.
  The server builds it, from capped plain-text pairs, so a page can't send arbitrary instructions. It is sent with
  the first question of a conversation and again only when the view changes (remembered per person and
  conversation in memory; after a restart it is simply sent again). The panel shows the question on its own, and the
  context as chips the person can remove before sending ("Sending with your question: Period = …").
- **Polling.** `ask` returns at once with the conversation and message ids. The page polls the portal (from 1.5 s,
  backing off to 5 s) and stops after 5 minutes. When the answer is complete the portal fetches up to 200 rows of
  the result, in the same strings-or-null shape as datasets. One question runs at a time.
- **Failures** from Genie are never a 500: no access to the space (403), not consented to the scope (403), busy (429),
  conversation gone (404), anything else (503), each with a plain sentence. A failed or cancelled message comes back
  as that status with Genie's reason.
- **Usage** records `genie_ask` and `genie_feedback` events, without the question text.

## Development workflow
See [AUTHORING.md](AUTHORING.md) for building a dashboard and [PROMOTION.md](PROMOTION.md) for releasing it. In short:
scaffold with `scripts/new_dashboard.py`, write SQL and the page, run `scripts/run_local.ps1` (or `run_local.sh`)
with your CLI profile and warehouse, pass `scripts/check.py` and `pytest`, then PR the same feature branch into
`develop`, `release` and `main` in turn.

## Deployment
Two example pipelines do the same thing; use whichever matches your git host.
- **Every PR:** `scripts/check.py --static` and `pytest` (Azure DevOps also runs `databricks bundle validate`).
- **Push to `develop` / `release` / `main`:** run every dataset with `LIMIT 0` against that environment's
  catalogs, build the source map, `databricks bundle deploy`, then `databricks bundle run portal`. Dev and test are
  stopped afterwards. Deploys to one environment run one at a time.
- **GitHub Actions** (`.github/workflows/deploy.yml`): GitHub environments `dev`, `test` and `prod`, each with a
  `DATABRICKS_HOST` variable and a service principal's OAuth secret (`DATABRICKS_CLIENT_ID`,
  `DATABRICKS_CLIENT_SECRET`), or GitHub OIDC instead of the secret. A `concurrency` group per environment.
- **Azure DevOps** (`azure-pipelines.yml`): the `databricks-service-connection` service connection (a placeholder);
  hosts come from the `lakeboard-<env>-vars` variable groups. `lockBehavior: sequential` per stage.
- **Apps:** `lakeboard` (prod), `lakeboard-test`, `lakeboard-dev`.

## Migrating a Power BI report
The playbook is in [MIGRATION.md](MIGRATION.md): find the report's users from the Power BI activity log, map the
report, rebuild and reconcile it, then cut over and retire the original.

## Who builds, who hosts
The intended model is that business teams build dashboards and the data team hosts them.
- **Business author:** builds a dashboard folder with an AI coding tool, optionally using Genie MCP to explore
  approved data. [BUSINESS_AUTHORS.md](BUSINESS_AUTHORS.md) explains the handoff. Every agent follows
  [DASHBOARD_WORKFLOW.md](DASHBOARD_WORKFLOW.md); `AGENTS.md` and the Claude skill both point there.
- **Automatic checks:** read-only SQL, allowed catalogs, declared parameters, no outside scripts, valid settings.
- **Data team review:** query cost and grain, access settings, and the reconciliation against the old report.
- **Platform:** the data team owns the shell, the kit, the pipeline, access and cost.

## Known gaps against Power BI
Email subscriptions, PDF or PowerPoint export, the mobile app, Teams embedding, data alerts and paginated
reports. The Power BI activity log shows how each report is consumed, which tells you which of these matter.

## Open questions
- Unity Catalog metric views for shared measures, so dashboards built by different teams use one definition.
- Pre-built tables for slow sources, so a page loads in seconds instead of waiting on a scan or a federated query.
- A usage table in Unity Catalog (`usage_table:`, off by default) for adoption reporting beyond the app log.
