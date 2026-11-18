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
Ask me about missing business definitions. Use LakeBoard's existing kit and theme.
Return a dashboard folder with dashboard.yml, index.html, sql files and README.md.
Include the checks you ran and anything the data team still needs to verify.
```

Review the draft with the agent: try the filters, explain what is confusing, and refine the layout. Compare its
figures with a trusted report or agreed examples. A convincing preview still needs its numbers checked.

## Ask the data team to host it

With repository access, hand off your branch or PR. Otherwise, send the dashboard folder through your team's
approved file-sharing process. Include the source and metric definitions, intended viewers, known gaps and
verification results in its README. Do not include credentials or downloaded business data in the folder.

The data team checks the folder, access settings and figures, adds it under `src/dashboards/<slug>/`, and follows
the normal review and release process. LakeBoard discovers valid folders automatically and adds them to the
configured navigation section; no separate application is required.

A preview link alone is not a deployable dashboard. The hosting format and the acceptance checks are the same
regardless of which agent built it. Deployment timing and availability are managed by your data team.
