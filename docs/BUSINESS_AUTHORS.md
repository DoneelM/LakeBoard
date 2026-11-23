# Build your own dashboard

You can describe a dashboard to a coding agent and have it build a LakeBoard folder. Use Claude Code, Codex,
Cursor or another agent that can write files. If your agent has an approved Databricks Genie One MCP connection,
use it to explore the data and clarify business metrics before building.

The data team reviews and hosts the result in the shared app. You do not need to create or deploy your own
Databricks App.

## Start with the business question

Tell the agent who will use the dashboard, what decision it should help with, the measures and filters you need,
and who should be allowed to see it. A screenshot, sketch or existing Power BI report can provide context.
For an existing report, include its semantic model definitions as well as its page definitions.

Ask the data team which Databricks Genie One MCP connection, datasets, navigation section and access groups
to use. The agent should ask for missing information rather than guess a definition such as revenue, active
customer or margin.

Databricks Genie One MCP supports data discovery, business questions and SQL generation across the data you
can access. Your data team can use the [Databricks connection guide](https://docs.databricks.com/aws/en/agents/mcp-tools/genie-mcp)
to configure it. This authoring connection is separate from the optional Ask Genie bar inside a hosted dashboard,
which uses a curated Genie agent configured by the data team.

## Keep the SQL, not the question

Every number on a hosted dashboard comes from a SQL file the data team can read, run and review. Ask Genie to
draft a query, open "Show code", and keep that SQL. **Never make the page ask Genie** for its numbers.

The lesson behind this rule: an artifact that refreshed through natural-language Genie questions had no SQL written
down. Before it could be hosted, the data team had to rebuild every query and reconcile the results week by week.
Building with the SQL saved from the start means it is reviewed once and nothing has to be rebuilt.

There are two routes:

1. **Build in the repository (preferred).** Follow [Build in the repository](#build-in-the-repository) below. It is
   the quickest way to a hosted dashboard.
2. **Prototype somewhere else, such as a Claude Dashboard artifact.** Fine for trying an idea, but **every dataset
   must carry its SQL**, not a Genie question. Paste the SQL from Genie's "Show code" into the artifact. The
   [import route](AUTHORING.md#importing-a-claude-dashboard) can then bring its SQL across unchanged.

## Give the agent the LakeBoard instructions

Open the repository in your coding tool. If you cannot access it, ask the data team for `AGENTS.md`,
`docs/DASHBOARD_WORKFLOW.md`, `docs/AUTHORING.md` and the City Trips example folder. A Power BI migration
also needs `docs/MIGRATION.md`. The agent needs the files themselves, not just their names.

Use this prompt, replacing the bracketed details:

```text
Build a LakeBoard dashboard following AGENTS.md and docs/DASHBOARD_WORKFLOW.md.
Use docs/AUTHORING.md for the supported APIs and City Trips as the example.

Question to answer: [business question and audience]
Title and owning team: [title; team]
Navigation section and allowed viewers: [section; groups agreed with the data team]
Data or existing report: [approved sources or Power BI project]
Measures, filters and interactions: [requirements]
Design reference: [optional screenshot or sketch]

Use the connected Databricks Genie One MCP tools, if available, to clarify sources and metric definitions.
Keep every query as SQL in sql/; never make the page ask Genie for its numbers.
Ask me about missing business definitions. Use LakeBoard's existing kit and theme.
Return a dashboard folder with dashboard.yml, index.html, sql files and README.md.
Include the checks you ran and anything the data team still needs to verify.
```

Review the draft with the agent: try the filters, explain what is confusing, and refine the layout. Compare its
figures with a trusted report or agreed examples. A convincing preview still needs its numbers checked.

## Build in the repository

### One-time setup

1. **Repository access.** Ask the data team for access to create branches and pull requests (on GitHub, a fork
   works too). You don't need, and shouldn't have, permission to merge.
2. **Install** Git, Python 3.11 and your coding agent.
3. **Databricks CLI, signed in as you:** `databricks auth login --host https://<your Databricks workspace>` and give
   the profile a name when asked. Use that name below as `<your profile>`.
4. **A SQL warehouse.** Ask the data team for `CAN USE` on a SQL warehouse, and for its ID.
5. **Clone the repository** and open the folder in your coding agent.

### The steps

1. **Make a branch from `main`:** `git switch -c feature/<your-dashboard> origin/main`. Never work on `main`,
   `release` or `develop` directly.
2. **Create the dashboard folder:**
   `python scripts/new_dashboard.py <slug> "<Title>" --owner <Team> --section <Section>`.
   The slug is lowercase letters, digits and hyphens; it becomes the address `/d/<slug>`.
3. **Write the queries** as above: one `SELECT` per `sql/<name>.sql`, tables as `catalog.schema.table`, filter
   values as `:name` parameters declared in `dashboard.yml`.
4. **Build the page** with the `dash` and `kit` building blocks. Your agent knows them from
   [AUTHORING.md](AUTHORING.md).
5. **Run it on your machine:** `./scripts/run_local.ps1 -Profile <your profile> -Warehouse <warehouse id>` (or
   `./scripts/run_local.sh <your profile> <warehouse id>`), then open `http://localhost:8000/d/<slug>`. It runs as
   you, so you only see data you can already query.
6. **Check it:** `python scripts/check.py --static`, then `python -m pytest -q`. Both must pass.
7. **Write the dashboard's `README.md`:** what it replaces, who owns it, what each dataset is, and a reconciliation
   of its numbers against a trusted report (same period, side by side, differences explained).
8. **Commit, push and open a pull request** using the template: into `develop` for a team that deploys LakeBoard
   through `develop`, `release` and `main` ([PROMOTION.md](PROMOTION.md)), whether on GitHub or Azure DevOps.
   Link the issue or work item if there is one.
9. **The data team reviews it** and promotes it. You sign off the numbers in the test environment.

### What you can and can't change

- You change **your dashboard folder only**: `src/dashboards/<slug>/`.
- The data team decides **who can see it** (`groups`), `auth: app`, shared caching and pre-loading
  (`cache: shared`, `warm`), and everything outside your folder (the portal, scripts, pipelines). If you need one
  of these, say so in the pull request.

### What the data team checks

- **SQL cost and grain:** the query scans no more than it needs, and each row means what the README says.
- **Access:** who can open the page, and whether those people may read the data.
- **Reconciliation:** the README shows the numbers match the report it replaces.
- **The page itself:** its code is reviewed before it goes live, and it uses the portal's theme.

Branch protection (GitHub) or branch policies (Azure DevOps) enforce this: a pull request, the checks, and an
approval from the data team.

Your coding agent reads [AGENTS.md](../AGENTS.md), so it knows the rules. It won't run grants, start or stop
apps, or deploy; the data team does those.

## Ask the data team to host it

With repository access, hand off your branch or PR. Otherwise, send the dashboard folder through your team's
approved file-sharing process. Include the source and metric definitions, intended viewers, known gaps and
verification results in its README. Do not include credentials or downloaded business data in the folder.

The data team checks the folder, access settings and figures, adds it under `src/dashboards/<slug>/`, and follows
the normal review and release process. LakeBoard discovers valid folders automatically and adds them to the
configured navigation section; no separate application is required.

A preview link alone is not a deployable dashboard. The hosting format and the acceptance checks are the same
regardless of which agent built it. Deployment timing and availability are managed by your data team.
