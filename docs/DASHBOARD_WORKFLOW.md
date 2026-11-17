# Create or change a dashboard with any coding agent

This is the shared workflow for Claude Code, Codex, Cursor and other coding agents. Read the repository's
[AGENTS.md](../AGENTS.md) first. [AUTHORING.md](AUTHORING.md) is the manifest, SQL and page API contract; use
[City Trips](../src/dashboards/city-trips/) as the worked example. Tool-specific entry points link here rather
than carrying their own checklist.

LakeBoard hosts ordinary files. It does not call the authoring agent when serving a dashboard. Use the agent's
repository tools when available; an artifact or chat preview is optional and is not the hosting format.

## 1. Establish the brief

Use the request and existing project context to identify the question the dashboard answers, its audience,
title, owning team, navigation section, source data, measures, filters and who may open it. Ask only for missing
information that affects those choices. Do not ask again for details already supplied.

For a Power BI migration, read [MIGRATION.md](MIGRATION.md). Inspect both the report and its semantic model,
including referenced model definitions. Map pages, measures, relationships, slicers, defaults and security roles;
record missing definitions and unsupported interactions before claiming equivalence.

For live checks, use only a Databricks CLI profile and warehouse explicitly chosen by the user. An existing
Databricks Genie One MCP connection can supply data context and query results through its exposed tools;
do not assume its tool names or select a different identity. If access is unavailable, continue the work that can be checked
offline, identify the missing schema or metric definitions, and report the remaining live checks.

## 2. Discover the data and definitions

When Databricks Genie One MCP is connected, use the available discovery and question-answering tools to identify
approved tables or metric views, dimensions, measures, units, date coverage and business definitions. Treat returned SQL
as a candidate to inspect and validate, not a guarantee of correct totals or joins. Reuse existing governed
metrics when available so the dashboard and Genie agree.

Databricks Genie One MCP is the authoring-time connection for cross-data discovery, business questions and SQL
generation. It is separate from the per-dashboard Genie agent behind the optional Ask Genie bar; configuring
that runtime integration is described in [AUTHORING.md](AUTHORING.md#ask-genie-optional).

Keep a short record of the source names, definitions and checks in the dashboard README. Do not put tokens,
people's data or private query results in the repository. Missing catalogs, libraries or navigation sections
need a separate platform change; do not silently edit shared configuration for a dashboard-only task.

## 3. Build the dashboard folder

In a repository checkout, follow [PROMOTION.md](PROMOTION.md) and branch from `main`, then scaffold:

```bash
python scripts/new_dashboard.py <slug> "<Title>" --owner <Team> --section <Section>
```

Keep dashboard changes inside `src/dashboards/<slug>/`:

| File | Deliverable |
|---|---|
| `dashboard.yml` | Title, description, owner, section, access settings, datasets and declared parameters |
| `sql/*.sql` | One read-only `SELECT`/`WITH` per dataset, aggregated to the required grain |
| `index.html` | Dashboard content using the documented `dash` and `kit` APIs |
| `README.md` | Sources, metric definitions, intended differences, reconciliation and verification results |

Use allowed prod catalog names and bound `:name` parameters. Keep viewer authorization and per-viewer caching
unless the task explicitly calls for another documented mode; shared results must be appropriate for every
permitted viewer. Do not create tables, metric views, Genie agents or grants as part of dashboard authoring.
These are separate platform/data tasks. An existing Genie agent can be referenced in the manifest as documented
in [AUTHORING.md](AUTHORING.md#ask-genie-optional).

Use `kit` for supported components, `kit.fmt` for numbers and dates, and the portal's CSS theme variables.
Use bundled d3 only for visualizations the kit does not provide. Include loading, empty, error and partial-result
states, keyboard access and a layout that works at phone width. Supply the current view with
`dash.genieContext` when browser-only filters should accompany Genie questions.

## 4. Adapt previews to the hosting contract

An agent may prototype in its own preview, but the final page must work in LakeBoard. Follow
[AUTHORING.md](AUTHORING.md#prototyping-in-another-tool) when adapting it. Remove preview-only APIs, bundled
copies of portal libraries and external dependencies. Do not require a particular agent, model API key,
React build step or artifact service to render the page. Verify against the actual portal runtime.

An author without repository access can work from the shared instructions, API reference and sample folder
provided by the data team. Return the same four-part folder to the maintainer; do not substitute a screenshot,
preview URL or standalone HTML file with embedded production data. The maintainer puts it under
`src/dashboards/<slug>/` on a branch and runs the checks below. No dashboard-specific app or route is needed.

## 5. Verify and hand off

From the repository root, run:

```bash
python scripts/check.py --static
python -m pytest -q
PORTAL_ENV=dev python -m pytest -q
```

For PowerShell, use the environment-switching command in [AGENTS.md](../AGENTS.md). With the user's chosen
profile and warehouse, check the SQL, then run the local portal:

```bash
python scripts/check.py --env dev --profile <profile> --warehouse <id>
./scripts/run_local.sh <profile> <id> dev
# Windows: ./scripts/run_local.ps1 -Profile <profile> -Warehouse <id> -Env dev
```

Open `/d/<slug>` and check loading, filters, drill-downs, exports, empty and error states, keyboard use, narrow
layout and console errors. `LIMIT 0` checks SQL shape; validate actual values separately. For migrations,
compare Power BI and LakeBoard under matching periods and filters and record discrepancies for owner review.

Return the folder, what it shows, the checks actually run and anything still unverified. Authors without command
or browser tools must say so; their handoff still needs maintainer validation. Prepare the PR using the repository
template and promotion flow when requested. Leave grants, bundle deployment and starting or stopping hosted
Databricks Apps to a person, as required by [AGENTS.md](../AGENTS.md).
