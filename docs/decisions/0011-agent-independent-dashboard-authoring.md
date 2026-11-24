# 0011. Agent-independent dashboard authoring

- **Status:** In progress

## Context

LakeBoard's runtime accepts dashboard files from any author, but its most complete agent checklist lived in a
Claude Code skill. The design also described Claude artifact compatibility as a goal. Business authors need
to build with their preferred coding agent, use Databricks Genie One MCP for data context, and hand work to
the data team.

## Decision

- Keep one workflow in `docs/DASHBOARD_WORKFLOW.md`, linked from `AGENTS.md` and the Claude skill.
- Keep the file format and supported `dash`/`kit` APIs in `docs/AUTHORING.md` as the hosting contract.
- Prefer direct repository authoring. External previews are optional and must be adapted to that contract.
- Document repository and folder-handoff routes for business authors in `docs/BUSINESS_AUTHORS.md`.
- Use connected Databricks Genie One MCP tools when available to clarify sources and definitions. Query results
  and generated SQL still need validation. Schema objects, permissions and hosted-app operations remain separate tasks.
- Distinguish authoring-time Databricks Genie One MCP from the optional runtime Ask Genie integration, which
  continues to use a curated Genie agent per dashboard.
- Keep agent-specific entry points thin. Authors whose tools do not discover repository rules can explicitly
  provide the same shared instructions and example.

- Every hosted number comes from a SQL file in the dashboard folder. A page never asks Genie for its numbers, and a
  prototype (for example a Claude Dashboard artifact) keeps the SQL from Genie's "Show code" for each dataset.
  `docs/BUSINESS_AUTHORS.md` gives business authors the repository route step by step (setup, branch, scaffold,
  local run, checks, reconciliation, pull request on GitHub or Azure DevOps) and says what the data team checks.
  Both pull request templates ask for it.

## Why

One maintained workflow reduces drift between tools. The data team reviews the same folder and evidence
regardless of which agent wrote it. Business authors do not need their own application or deployment access.
An artifact that refreshed through natural-language Genie questions had no SQL written down; hosting it meant
rebuilding every query and reconciling it week by week. Keeping the SQL from the start avoids that rework.

## Limitations

Agents differ in tool access and output quality; this is a common contract, not proof that every agent produces
equivalent dashboards. An isolated preview may depend on APIs or libraries LakeBoard does not provide.
File handoff still needs maintainer validation and the normal release process. There is no upload-and-publish UI
or automatic conversion of arbitrary HTML, Power BI semantics, metric views or Genie configurations.

## Alternatives considered

- Separate full workflows per agent: duplicates instructions and makes fixes easy to miss.
- Require Claude artifacts: excludes repository-based authors without improving the hosting contract.
- Accept arbitrary generated pages: bypasses the shared APIs, validation and access review.

## Changing it later

Update the shared workflow and API reference together when the contract changes. Add tool-specific adapters
only when needed for discovery, and point them to the shared workflow. Record runtime or publication changes
separately.

## Links

- [0001](0001-one-app-one-folder-per-dashboard.md)
- [Shared workflow](../DASHBOARD_WORKFLOW.md), [Business authors](../BUSINESS_AUTHORS.md)
- [API contract](../AUTHORING.md), [Repository rules](../../AGENTS.md)
