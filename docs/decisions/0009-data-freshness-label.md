# 0009. Data freshness label

- **Status:** Accepted

## Context

People press "Refresh data" without knowing how old the data on screen is. They also can't tell if the source has
changed since. Often it hasn't, so the refresh re-runs queries for nothing, and for shared data the new result
replaces the old one for everyone. Datasets are cached in different ways (per person, shared, pre-loaded, read by the
app), and the page didn't say which.

## Decision

- The title bar shows `Data as of 10:42 am · 12 min ago` beside Refresh data. The time is the **oldest** fetch time
  among the datasets the page has loaded, shown in the portal's time zone (`warm.timezone`, UTC unless set).
- Clicking the label opens a panel. For each dataset it shows when the data was fetched, when the cached copy
  expires, and the cache type in plain words.
- A dataset can have an optional `source:` note in `dashboard.yml`: one short sentence (at most 200 characters)
  saying how the source is built.
- The portal finds out when each dataset's source tables last changed, by itself. `GET /api/d/<slug>/sources`
  reads Unity Catalog table metadata (the Tables API). It follows each view to the tables it reads, through
  `view_dependencies`, and uses those tables' `updated_at`. A view's own `updated_at` is only when its DDL last
  changed, so it is never used.
- That lookup runs as the app's service principal. It reads metadata only, so it costs no warehouse time. Results
  are cached for 10 minutes per table.
- If every source table is older than the data on screen, the label adds "· source unchanged". If one is newer, it
  adds "· newer data available". Otherwise it adds nothing.
- The service principal needs `BROWSE` on each catalog involved: the catalog the dashboards read and every catalog
  their views read from. BROWSE shows metadata, never rows. `scripts/grant_app_access.py` prints the grant for each
  environment.

## Why

- Using the oldest fetch time means the label never says the page is fresher than its stalest part.
- Showing the source change time answers the real question, "will Refresh show anything new?", without anyone
  needing to know the pipeline schedule.
- Metadata calls are cheap and quick, and they work even when the viewer can't read the tables behind the views
  they query.
- The `source:` note adds what metadata can't tell people: who builds the data and when.

## Limitations

- "Changed" means the table was written. A rebuild that writes identical data still counts as a change, so the label
  errs toward suggesting a refresh.
- Source tables that are loaded often (every few minutes) will nearly always show "newer data available".
- Federated (for example Snowflake) and external tables, and functions, give no usable change time. See "Live and
  external sources" below for how they are counted. A table the app can't see still hides the cue.
- SQL that depends on today's date can return different rows even when no source changed.
- The fetch time is when the portal ran the query, not when the source was built.
- A catalog listed under `static_catalogs` is trusted to never change. If someone does write to it, the label won't
  notice.
- Each environment needs the BROWSE grant. Without it the panel says "Source change time unavailable". The Tables
  API docs list only USE CATALOG, USE SCHEMA and SELECT, while the privileges docs say BROWSE allows reading
  metadata; confirm in your workspace that BROWSE alone is enough.
- The label checks the source every 5 minutes, so a change can take that long, plus the 10-minute cache, to show.

## Live and external sources

If every FOREIGN (federated) or EXTERNAL table counted as unknown, one such table would hide the cue for the whole
dataset. Dashboards that read a federated table beside many managed ones would never show a cue.

So each table has a kind:

- `managed`: timed.
- `live`: a FOREIGN table. Every query reads the remote system, so the data is current when it is fetched. The
  panel says "live (Snowflake)" when the table's `data_source_format` names the system, otherwise "live, federated".
- `external`: written outside Unity Catalog; "external, change time not tracked".
- `unknown`: no permission, not found, timed out or over the table limit.

The dataset's time is the newest managed table's, as long as there is one and no table is unknown. Live and
external tables don't block it. The summary adds `live` and `partial` flags, the panel says the time covers the
tracked tables only, and with a live table the label says "· tracked sources unchanged" rather than "· source
unchanged", because a live source can change without the portal knowing. A dataset that reads only live tables gets
no time and no cue ("Live source — always current when fetched"): "newer data available" can't be worked out
honestly for it. `grant_app_access.py` also lists BROWSE for federated and external catalogs, so the app can read
those tables' type; without it they are unknown and the cue stays hidden.

Why: a rule that hides the cue whenever any table is untimed is safe, but hides it on the dashboards where people
most want it. Saying which part the time covers is more useful than saying nothing.

## The view map is built at deploy

With BROWSE only, the Tables API returns a view's type but no `view_dependencies`. The service principal has SELECT
only on the views that warmed and `auth: app` datasets read, so every other view would come back with no
dependencies, be unknown, and hide the cue. Table `updated_at` and FOREIGN types do work with BROWSE.

So the deploy pipeline runs `scripts/build_sources_map.py`, as the pipeline identity (which sees full metadata). It
follows every view behind the environment's live dashboards (same depth and table limits) and writes
`src/sources_map.json`: each view's dependencies and each table's type. The app loads the map at start-up if it was
built for its environment and follows views through it; views not in the map are looked up as before. Tables are
still looked up live, so the times stay current; a failed table lookup is still unknown. The step only warns if it
fails, and without a map the app looks views up itself. The service principal still needs only BROWSE.

Rejected: SELECT on every view for the service principal (widens its data access for a label); lineage system
tables (warehouse cost on every check, and they lag).

## Views that read no table

A view such as a generated calendar (`date_vw` built from `sequence()`) reads no table. The deploy map records it
with no dependencies. Treating "no dependencies" as unknown would block the dataset's time.

So a table has a fifth kind, `none` ("reads no table"), for a view that is **known** to read no table: the deploy
map lists it with `[]`, or a lookup with full metadata access returned a dependency list holding no table. A `none`
table blocks nothing. If every table of a dataset is `none`, the dataset gets `source_updated_at: null` and
`no_source: true`, and the panel says "No source table (generated in the query)"; with managed tables as well, the
time comes from the managed ones. On the page, such a dataset can't have newer data, so it neither blocks "source
unchanged" for the other datasets nor produces a cue itself.

A BROWSE-only lookup also returns a view with no dependencies, because it returns no `view_dependencies` at all.
That says nothing about what the view reads, so it stays `unknown`. This is the reason the deploy map exists, and
the map is the main source of `none`.

Not verified: whether the Tables API returns an empty `view_dependencies` (rather than omitting it) for a view with
full access and no table dependency. If it omits it, a live full-access lookup leaves that view `unknown`; the
deploy map, which is how the app learns about views, is unaffected.

## Static catalogs

Tables in the built-in `samples` catalog report `updated_at` as the moment you ask. So the sample dashboards said
"newer data available" right after loading, though that data never changes.

So `src/environments.yml` has `static_catalogs` (default `[samples]`): catalogs whose data never changes, or whose
`updated_at` means nothing. A table in one of them has a sixth kind, `static`. It is never looked up (no API call, no
BROWSE grant), has no time and blocks nothing. A dataset whose tables are all `static` (or `none`) gets
`source_updated_at: null` and `static: true`; the panel says "Never: this data doesn't change". If every dataset on
the page is static, the label says "· source never changes". Mixed with managed tables, the time comes from the
managed ones. The deploy map leaves static tables out. The dev and test names of a listed catalog count too.

Why: a time we know is wrong is worse than no time. Listing the catalogs is simple and explicit; guessing from the
time ("updated in the last few seconds") would also hide real, frequent loads.

## Alternatives considered

- **Only a free-text `source:` note.** This is simple, but it goes out of date and can't say whether this
  particular refresh would help. We kept it as an addition, not the whole answer.
- **`DESCRIBE HISTORY` or `information_schema` on the SQL warehouse.** This costs warehouse time on every check,
  and the viewer often can't read the underlying tables.
- **Lineage system tables.** These show table-to-table lineage, but they lag behind and still need the warehouse.
  `view_dependencies` already gives what we need.

## Changing it later

- A new view is followed by the app itself until the next deploy rebuilds the map (`python
  scripts/build_sources_map.py --env <env> --profile <your-profile>` builds it locally).
- The cache times and limits are constants at the top of `src/portal/sources.py`.
- To trust another table type (for example external Delta tables), add it to `TRUSTED_TYPES` there. FOREIGN
  tables are in `LIVE_TYPES`; `VIA` maps a foreign table's format to the system name shown in the panel.
- To turn the cue off, remove the BROWSE grant. The label then shows only the fetch time.

## Links

- [OPERATIONS.md, "The freshness label"](../OPERATIONS.md)
- [DESIGN.md, "Freshness label"](../DESIGN.md)
- [AUTHORING.md, `source:`](../AUTHORING.md)
- Unity Catalog Tables API, get a table: https://docs.databricks.com/api/workspace/tables/get
- Unity Catalog privileges (BROWSE): https://docs.databricks.com/aws/en/data-governance/unity-catalog/manage-privileges/privileges
