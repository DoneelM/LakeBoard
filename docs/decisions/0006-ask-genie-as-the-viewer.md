# 0006. Ask Genie: as the viewer, one Genie space per dashboard

- **Status:** Accepted

## Context
Databricks AI/BI dashboards have a Genie bar for questions in plain English. We wanted the same on portal
dashboards. The answers must use the same data and definitions as the dashboard, and the same access rules.

## Decision
- A `genie:` block in `dashboard.yml` names a Genie space id per environment, plus `about` text and up to five
  sample questions. No id for an environment means no chat bar there.
- The portal's backend calls the Genie Conversation API with the viewer's token (the app's `genie` user scope). It
  never calls Genie as the app's service principal, and the bar is refused on dashboards with `auth: app` data.
- The page describes its current view (filters, scope) with `dash.genieContext()`. The API has no context field,
  so the server puts a short plain-text preamble before the question: title, `about`, SQL parameters and the page's
  view. It is sent with the first question and again when the view changes.

## Why
- A curated space holds the tables, instructions and example SQL that keep answers close to the dashboard.
- As the viewer, Unity Catalog row filters apply to Genie's queries too, and Genie's history shows the real person.
- Many pages filter in the browser, so Genie can't otherwise know the period or region on screen.

## Limitations
- Only where a space exists. A dashboard often has a space in prod only, so there is no Genie bar in dev or test.
- Viewers need `CAN RUN` on the space and `SELECT` on its tables. Giving the portal's viewers group `CAN RUN` is a
  separate decision for each space.
- Each viewer consents once to the `genie` scope.
- A space answers for whatever scope its instructions default to (for example the whole company rather than one
  division), so the context preamble matters. Without it, answers can differ from the page.
- Answers come from the space's own instructions and SQL, not the dashboard's `sql/` files, so they can drift apart.
  Check a few answers against the page before you switch the bar on.
- Questions are not cached; each runs SQL on the space's warehouse.

## Alternatives considered
- **Genie One (workspace-wide Genie).** Its API was in Beta when this was decided, and it can't be scoped to one
  dashboard's data.
- **The AI/BI dashboard approach.** Those dashboards use a hidden companion space through internal endpoints that
  we can't call.
- **Genie as the app's service principal.** Everyone would see what the app can read, and row filters would stop
  applying.

## Changing it later
Add a space id for dev or test in the dashboard's `genie:` block to switch the bar on there. Removing the block
removes the bar. The `genie` scope is in `resources/portal.app.yml`.

## Links
- [DESIGN.md](../DESIGN.md) "Ask Genie"; [OPERATIONS.md](../OPERATIONS.md) "Ask Genie"; [AUTHORING.md](../AUTHORING.md)
  "Ask Genie (optional)"
- `src/portal/genie.py`, `src/static/genie.js`, `src/static/dash.js` (`genieContext`)
