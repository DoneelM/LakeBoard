# 0011. Agent-independent dashboard authoring

- **Status:** In progress

## Context

LakeBoard's runtime accepts dashboard files from any author, but its most complete agent checklist lived in a
Claude Code skill. The design also described Claude artifact compatibility as a goal. Business authors need
to build with their preferred coding agent, use Genie MCP for data context, and hand work to the data team.

## Decision

- Keep one workflow in `docs/DASHBOARD_WORKFLOW.md`, linked from `AGENTS.md` and the Claude skill.
- Keep the file format and supported `dash`/`kit` APIs in `docs/AUTHORING.md` as the hosting contract.
- Prefer direct repository authoring. External previews are optional and must be adapted to that contract.
- Document repository and folder-handoff routes for business authors in `docs/BUSINESS_AUTHORS.md`.
- Use connected Genie MCP tools when available to clarify sources and definitions. Query results and generated
  SQL still need validation. Schema objects, permissions and hosted-app operations remain separate tasks.
- Keep agent-specific entry points thin. Authors whose tools do not discover repository rules can explicitly
  provide the same shared instructions and example.

## Why

One maintained workflow reduces drift between tools. The data team reviews the same folder and evidence
regardless of which agent wrote it. Business authors do not need their own application or deployment access.

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
