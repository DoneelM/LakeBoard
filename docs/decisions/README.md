# Decision records

A decision record is a short note on one feature or design decision: what we decided, why, what it costs us, and what
else we looked at. Write one for every feature or design decision, in the same pull request as the change. If you
track work in an issue tracker, link the record from the issue; the record in this folder is the master copy. When a
decision changes, update the record (for a small correction) or write a new one that supersedes it (for a new
decision). Don't rewrite history: mark the old record "Superseded by NNNN" and leave its text as it was.

## Template

Copy this into `NNNN-kebab-title.md`, using the next free number.

```markdown
# NNNN. Title

- **Status:** Accepted | Superseded by NNNN | In progress
- **Date:** YYYY-MM-DD (the date the main pull request merged)
- **Links:** issue and pull requests, if any

## Context
What problem or situation led to this. Facts only.

## Decision
What we do. Specific: settings, files, names.

## Why
The reasons, short.

## Limitations
What this costs or doesn't cover. Honest and specific.

## Alternatives considered
What else we looked at, and why not.

## Changing it later
Where the setting lives and what it would take to change.

## Links
Docs sections, files, pull requests.
```

Keep it to about a page. Plain English, short sentences.

## Index

Numbers are never reused. Gaps in the sequence are records that were specific to one deployment and are not part of
this repository.

| No. | Title | Status |
|---|---|---|
| [0001](0001-one-app-one-folder-per-dashboard.md) | One app, one folder per dashboard, same SQL everywhere | Accepted |
| [0002](0002-queries-run-as-the-viewer.md) | Queries run as the viewer; `auth: app` is the exception | Accepted |
| [0003](0003-caching-and-warming.md) | Caching and warming | Accepted |
| [0004](0004-promotion-same-branch-to-each-environment.md) | Promotion: the same branch to each environment | Accepted |
| [0005](0005-stop-apps-after-deploy-and-at-6pm.md) | Dev and test apps stopped after every deploy; prod stopped in the evening | Accepted |
| [0006](0006-ask-genie-as-the-viewer.md) | Ask Genie: as the viewer, one Genie space per dashboard | Accepted |
| [0009](0009-data-freshness-label.md) | Data freshness label | Accepted |
| [0010](0010-local-overrides-for-workspace-details.md) | Workspace details in gitignored local files | Accepted |
| [0011](0011-claude-dashboard-artifacts.md) | Claude Dashboard artifacts run as-is | Accepted |
| [0012](0011-agent-independent-dashboard-authoring.md) | Agent-independent dashboard authoring | In progress |
| [0013](0013-platform-reliability.md) | Shared access, warm policy and honest freshness | Accepted |
| [0014](0014-travel-operations-showcase.md) | Travel Operations personal showcase | Accepted |
| [0015](0015-review-deployed-apps.md) | Review deployed apps | Accepted |
| [0016](0016-selective-refresh.md) | Selective refresh and query profiling | Accepted |
| [0017](0017-navigation-sub-menus.md) | Navigation sub-menus (`group:`) | Accepted |
| [0018](0018-publishing-guards.md) | Publishing guards: reviewed pages and shared SQL, groups for app data, credential-free PR checks | Accepted |
