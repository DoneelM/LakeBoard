# Running the portal

## Access

Access is decided in four places, from widest to narrowest.

| Level | Where it is set | Effect |
|---|---|---|
| The portal | `CAN USE` on the Databricks App: the `viewers_group` variable in `databricks.yml` (default `lakeboard-users`, a placeholder), plus any groups added per target | Who can open the portal at all |
| A dashboard | `groups:` in its `dashboard.yml` | It only appears in the left navigation, and only opens, for those groups |
| Part of a dashboard | `groups:` on one dataset in `dashboard.yml` | The server refuses that dataset to everyone else. The page checks `dash.allowed('id')` to hide the section |
| The data itself | Unity Catalog grants, row filters and column masks | Queries run as the viewer, so this always applies, whatever the page does |

### Restricting part of a dashboard (example: prices)

Say a dashboard shows contract prices to everyone who can open it. To limit that section to some people:

1. Put the sensitive columns in their own dataset, for example `prices`.
2. List the allowed groups on it:
   ```yaml
   datasets:
     prices:
       sql: sql/prices.sql
       groups: [pricing-viewers]
   ```
3. In the page, hide the section for everyone else: `if (!dash.allowed('prices')) { /* don't draw the Prices tab */ }`.
4. For data that must be protected everywhere, not only in this dashboard, also restrict it in Unity Catalog
   (revoke `SELECT` on the view, or add a column mask). The portal setting controls what the dashboard shows; Unity
   Catalog controls what the person can query anywhere.

Group names are the group display names as they appear in the Databricks workspace (account groups, or groups
synced from your identity provider). The portal caches each person's groups for one minute, so a removed
membership stops counting within about a minute (plus however long Databricks takes to propagate it).

An `auth: app` dataset is read as the app's service principal, so Unity Catalog no longer protects it per viewer.
The checks refuse one unless both the dashboard and the dataset name their `groups:`
([decision 0018](decisions/0018-publishing-guards.md)).

### The sample dashboards

The sample dashboards (City Trips, Sales & Margin, Bakery Franchises, Travel Marketplace, Guest Experience,
Omnichannel Retail and World Weather) read the built-in `samples` catalog, which every user in the
workspace can usually read. They have `groups: []`, so everyone who can open the portal sees them. Delete their
folders when you add your own, or keep them out of prod with `environments: [dev]`.

## Ask Genie

Dashboards with a `genie:` block show an "Ask Genie about this dashboard…" bar, in the environments that have a
space id. The sample dashboards ship without one; add your own space id to try it.

**Who can use it.** The portal asks Genie as the person viewing the page, never as the app. So a person needs:

| What | Where |
|---|---|
| The dashboard itself | Its `groups:` (as for the rest of the page) |
| `CAN RUN` (or `CAN VIEW`) on the Genie space | The space's Share dialog, usually granted to a group |
| `SELECT` on the tables and views the space reads | Unity Catalog (and the views they are built on) |
| `CAN USE` on the space's SQL warehouse | If the space uses the portal's own warehouse, anyone who can load the dashboard has it |

Someone without access to the space sees "You can't use Genie for this dashboard yet. Ask the data team for access
to its Genie space." Unity Catalog row filters and masks apply to Genie's queries as they do to the dashboard's.

**After the first deployment with Genie.** The app asks for the `genie` user scope as well as `sql`. Each person
is asked once to consent to the new scope the next time they open the portal. Nothing else changes for them. If a
workspace admin has limited which scopes apps may request (Settings → Development), `genie` must be allowed, or
the deployment fails.

**No chat bar** on a dashboard means one of: it has no `genie:` block, it has no space id for this environment, or
it failed validation (`/api/health`).

**Cost.** Each question runs one or more SQL statements on the Genie space's warehouse, as the viewer. Questions are
not cached. Genie also limits how many questions a workspace can ask per minute; when it is busy the panel says
"Genie is busy. Try again in a minute."

**Usage.** Each question writes a `genie_ask` usage event (and each thumbs up or down a `genie_feedback` event) with
the dashboard and the person, never the question. The questions themselves are kept by Genie, in the person's
conversation history in the space, where the space's managers can review them with the thumbs feedback.

## Starting and stopping (cost)

The app bills while it runs. The example pipelines stop dev and test after every deployment.

```bash
databricks -p <your-profile> apps start lakeboard-dev
```

```bash
databricks -p <your-profile> apps stop lakeboard-dev
```

Prod keeps running. To save cost out of hours, stop it in the evening with a scheduled Databricks job (a notebook
or script task running `databricks apps stop lakeboard`, or the SDK's `w.apps.stop("lakeboard")`). Nothing has
to start it again: the first person to open the portal does. Stopping empties the cache (see
[How data refreshes](#how-data-refreshes)). See decision 0005 for the reasoning.

## How data refreshes

The portal does not copy data. It runs each dataset's SQL on a SQL warehouse and keeps the result for a while, so the next person does not wait. This section explains how long, for whom, and what makes it run again.

### Where the cache lives

- The cache is in the app's memory. There is no table or file behind it.
- A deployment, a restart, or stopping the app empties it. If prod is stopped each evening, it starts each day with an empty cache.
- Each result is reused until its `cache_ttl` runs out (default 1 hour). An expired result is never served. The next request runs the query.
- Expired results are removed from memory once they are more than an hour past expiry.
- After a deployment or restart, the first load of each dataset is slow. The warming below is what avoids that for shared data.

### What one cached result is keyed on

A result is stored under: **dashboard + dataset + who + the filter values that dataset sends to SQL**.

- Filters that never reach SQL (they filter in the browser) are not part of the key. Changing them runs no query.
- **Who** is the viewer by default. Queries run as the viewer, so row-level security and column masks can give two people different rows. Their results are kept apart.
- Who is `shared` for `cache: shared` datasets, and `app` for `auth: app` datasets. One result then serves everybody.
- If identical requests arrive together, one query runs and the others wait and reuse it. This does not apply to Refresh (see below): a refresh always runs its own query.

### The modes

| Mode (in `dashboard.yml`) | Whose result | When it runs again | Use it for |
|---|---|---|---|
| Default | One per viewer, per filter combination. Runs as the viewer | When someone asks and the result is older than `cache_ttl`, or they press Refresh | Anything with row-level security, or data only some people may see |
| `cache: shared` | One for everybody, per filter combination. Runs as the first viewer to ask | Same as default | Data every viewer may see (no row-level security) |
| `cache: shared` plus `warm:` | As above | The same, and also in the background at the `warm.times` on weekdays (in `warm.timezone`) and once when the app starts. Only in the `warm.environments` (prod by default). Runs as the portal's service principal | Shared data that is slow and has a few common views, so people find it ready |
| `cache: shared` plus `warm:` and `warm_at: startup` | As above | Only once, in the background, when the app starts (in the `warm.environments`); never at the `warm.times`. After that, when someone asks and the result is older than `cache_ttl`, or they press Refresh. Runs as the portal's service principal | Slow shared data where scheduled runs would cost too much warehouse time, or data that doesn't change during the day. Pair it with a long `cache_ttl` (for example 24h) so the first viewer after start-up doesn't re-run it |
| `auth: app` | One for everybody. Runs as the portal's service principal, so viewers need no Unity Catalog access. It cannot take filters | Default (`background: true`): in the background every `cache_ttl` minus 5 minutes, never more often than every 5 minutes (after a failure it retries in 15 minutes). With `background: false`: only when someone asks and the result has expired | People who have no access to the tables themselves |

Notes:

- Warming times, the time zone (any IANA zone; default UTC) and the environments are under `warm:` in `src/environments.yml`.
- Warming needs the service principal to have read access to the views. `python scripts/grant_app_access.py --env prod --profile <your-profile> --warehouse <warehouse-id>` prints the grants, and `--apply` runs them. Run it for each environment that has `auth: app` or warmed datasets. Until that is done, warming fails quietly (it is logged) and the first viewer's query fills the cache instead.
- `warm_at` (optional, only with `warm:`): `schedule` (the default) warms at start-up and at each `warm.times`;
  `startup` warms only once, at start-up. See [Shared-result access and startup policy](#shared-result-access-and-startup-policy).
- Each `warm:` entry is one filter combination. Any other combination runs on first use.
- Use `cache: shared` only where every viewer may see the same rows. The result one person's query produced is shown to the next.
  Before a shared result is returned, LakeBoard still checks that this viewer may run the query
  ([below](#shared-result-access-and-startup-policy)); that protects the sources, not differences in rows.
- A scheduled warm re-runs the query even if the cached result is still fresh. It replaces the result and restarts the clock.

### Refresh data and Refresh all

- **Refresh data** checks the sources of datasets the page has already loaded. It reads each distinct source once
  from fresh Unity Catalog metadata and reruns a dataset's query if any source changed since the query began.
  It reuses valid results for unchanged direct managed Delta tables and fixed sample data, subject to the existing access checks.
- If LakeBoard cannot verify every input, it reruns the query. This includes views, external and federated tables,
  unavailable metadata, time-dependent SQL and datasets configured with `refresh: always`. A missing or expired
  result also needs a query. For a join, a change on either side reruns the complete dataset query.
- **Refresh all** bypasses the result cache for every loaded dataset. A dataset the page hasn't asked for yet still loads on demand.
  While any query on the page is still running, it does nothing and asks you to wait, so it never skips or duplicates a
  query. A second press of either button during a refresh is ignored.
- Every new result gets its own random ETag, so a result that replaced another never matches the old one's ETag, even
  when both were fetched within the same clock tick.
- A new shared or app-auth result replaces the shared cache entry. A per-viewer result replaces that viewer's entry.
  The page reports how many results were updated, unchanged or failed.
- Changing a filter that is sent to SQL reloads only the datasets that use it. They use the cache if it already holds that combination. Other filters work in the browser and run nothing.

### What the sample dashboards use

All sample dashboards read sample data that never changes and has no row-level security, so their datasets use
`cache: shared` with a long `cache_ttl` (6 to 24 hours). City Trips and Sales & Margin also `warm:` their default
filters once per process with `warm_at: startup`, so scheduled warms do not re-query fixed samples. Each dashboard's `dashboard.yml` says why in a comment.

### Example: a prod weekday

1. **Early morning.** The app is stopped (if you stop it overnight) and its cache is empty. The first person to open the portal starts it.
2. **App starts.** Warming runs once at start-up and fills every `warm:` entry. Anyone who opens one of those dashboards before it finishes runs the query themselves.
3. **First viewers.** Default datasets run as each person on first open. Later opens within the `cache_ttl` are instant. `auth: app` datasets run as the service principal and are reused for everyone.
4. **First warm time** (07:00 by default). The warm run re-runs every `warm:` entry and replaces the results, except datasets with `warm_at: startup`, which keep their start-up result until it expires. (If the app only just started, this repeats the start-up warm.)
5. **Midday.** Someone presses **Refresh data** on a shared dashboard. Loaded datasets whose sources changed, or can't be verified, re-run; the rest keep their result. (**Refresh all** re-runs every loaded dataset.) A new shared result is what everyone sees from then on.
6. **Second warm time** (13:00 by default). The warm run happens again, as at the first warm time.
7. **Evening.** If a job stops the app, the cache is gone. The next day starts again at step 1.

### Freshness is capped by the source

The cache only decides how often the portal asks again. It cannot make data newer than the table it reads. For example, if a pipeline rebuilds a table at 06:00, 10:00 and 14:00, a Refresh at 10:05 shows the 10:00 build. Asking more often adds nothing. A dataset's `source:` note is the place to say this to viewers.

### Why a first load can be slow

- Portal queries run on the SQL warehouse set per target in `databricks.yml`. If other tools (Power BI refreshes, notebooks) share that warehouse, queries queue before they start when it is busy. A serverless warehouse starts quickly and can scale out.
- A query is stopped after 10 minutes (`PORTAL_QUERY_TIMEOUT`) and returns at most 500,000 rows (`PORTAL_MAX_ROWS`). A result cut at the row limit is flagged to the page.
- A query that fails shows on the page as "Couldn't load this data" with the reason. A very long request can also time out at the Databricks Apps proxy before the app answers, and the page shows an error then too. Press Refresh to retry. (Nothing in this repo sets or shows the proxy's limit, so no figure is given.)
- If one slow dataset keeps causing trouble, use `cache: shared` with `warm:` (when everyone may see the same data), raise `cache_ttl`, or build a pre-aggregated table for it.

### Profile a slow dataset

Search the app's application logs for `dataset_query`. Each warehouse execution includes the dashboard and dataset,
Databricks statement ID when available, elapsed milliseconds and outcome. Elapsed time covers submission, wait and result
download. Result-cache hits do not generate a query event. The event omits SQL text, parameter values, result rows and
viewer identity.

Find the statement ID in Databricks SQL Query History and open its Query Profile. Compare scan bytes, file pruning
and execution time for the same parameters, warehouse and cache conditions, and verify the result still matches.
Performance Insights can suggest changes such as using the existing report date range to filter a clustering key.
[Query history](https://docs.databricks.com/aws/en/sql/user/queries/query-history) ·
[Query performance insights](https://docs.databricks.com/aws/en/sql/user/queries/performance-insights)

## Usage

Every page view writes one line to the app log:

```
portal.usage {"event": "view", "env": "prod", "user": "someone@example.com", "ts": 1794300000, "dashboard": "city-trips"}
```

Read them with `databricks -p <your-profile> apps logs lakeboard`, or in the app's Logs tab. App logs are
short-lived. For adoption reporting over months, also write the events to a Unity Catalog table. This is off by
default. To turn it on:

1. Create the table (it needs to be done once, by someone who may create tables in that schema):
   ```sql
   CREATE TABLE main_prod.governance.lakeboard_usage (
     event_time TIMESTAMP, event STRING, environment STRING, dashboard STRING, user_email STRING);
   ```
2. Name it under `usage_table:` in `src/environments.yml`, per environment.
3. Run `scripts/grant_app_access.py` for that environment; it adds `SELECT, MODIFY` on the table for the app.

Rows are written in batches every minute. A failed write is logged and dropped; it never affects a page.

## The freshness label

Beside **Refresh data** each dashboard shows `Data as of 10:42 AM · 12 min ago`. The time is the *oldest* fetch
time among the datasets the page has loaded, so the label never makes the page look fresher than its stalest part.
Times are in `warm.timezone` and written in the `locale:` format, both from `src/environments.yml`.
Clicking it opens a panel that lists, per dataset: when it was fetched, how long the portal keeps it ("Kept until"),
how it is cached (your own copy, shared, shared and pre-loaded, or read by the portal), the dataset's `source:`
note, when its source tables last changed, and (under "Source tables") each table with what is known about it.

- **"· source unchanged"** means the latest source metadata shows no newer write. **"· newer data available"**
  (in green) means a tracked source table changed after the fetch. Refresh data checks current metadata before deciding.
- **Kinds of table.** Managed tables (including materialized views and streaming tables) are timed: "changed 2 h ago
  (10:42 AM)". Federated (Lakehouse Federation, for example Snowflake or Fabric) tables are **live**: each query
  reads the remote system, so the data is current when fetched, but there is no change time. External tables are
  written outside Unity Catalog, so their change time isn't tracked. A table the app can't see, or one cut off by the
  time or table limit, is "change time unavailable".
- The dataset's time is the newest **managed** table's. Live and external tables don't block it; the panel then adds
  "Some sources are read live or aren't tracked; the time shown covers the tracked tables only", and when a live
  table is involved the label says **"· tracked sources unchanged"** instead of "· source unchanged". A dataset
  that reads only live tables shows "Live source — always current when fetched" and gives no cue.
- **"No source table (generated in the query)"** is a view that reads no table (for example a calendar view built
  from a sequence). It has nothing to time, gives no cue of its own and doesn't block the other datasets' cue. Mixed
  with managed tables, the time comes from the managed ones. It relies on the deploy map (below) saying the view has
  no dependencies; a view the app can only BROWSE is "change time unavailable", not this.
- **"Never: this data doesn't change"** is a table in a catalog listed under `static_catalogs` in
  `src/environments.yml` (by default `samples`, whose `updated_at` is just the moment you ask). These tables are
  never looked up, have no time and block nothing. If every dataset on the page reads only them, the label says
  **"· source never changes"**. Add a catalog there only if its data really never changes.
- **No cue** means the change time is unknown for at least one table (one the app can't see, or a lookup that ran
  out of time), or a dataset has no managed table at all.
- The change times come from the Unity Catalog Tables API (`GET /api/d/<slug>/sources`), called as the app's service
  principal. It follows each view to the tables it reads and uses their `updated_at`; a view's own time is only its
  last DDL change, so it is never used. It runs no SQL and costs nothing on the warehouse. Results are kept 10
  minutes per table (6 hours for what a view reads), and the page asks again every 5 minutes while it is visible.
- **The view map.** With BROWSE only, Unity Catalog doesn't say what a view reads. So each deploy runs
  `python scripts/build_sources_map.py --env <target>` ("Build the source map for the freshness label") before
  the bundle deploy. It writes `src/sources_map.json` (gitignored, uploaded through `sync.include` in
  `databricks.yml`) and prints how many views it mapped and which lookups failed. The app logs at start-up whether it
  loaded the map. If the step fails it only warns; the app then follows views itself, and views it can only BROWSE
  leave the cue out.
- **Grant (metadata only).** The service principal needs `BROWSE` on each catalog those views and tables live in,
  federated and external catalogs included (without it their type can't be read, they count as unknown, and the cue
  disappears).
  BROWSE shows metadata (names, types, last-modified time, view dependencies), never rows. After the first deployment,
  per environment:
  ```
  python scripts/grant_app_access.py --env <dev|test|prod> --profile <your-profile> --warehouse <warehouse-id>           # prints them
  python scripts/grant_app_access.py --env <dev|test|prod> --profile <your-profile> --warehouse <warehouse-id> --apply   # runs them
  ```
  The `BROWSE` lines are listed under "Metadata only". Until they are applied the label still shows the time and
  the panel shows "Source change time unavailable"; nothing fails. A table that can't be read is logged once as
  `source metadata for <table> unavailable`. The `samples` catalog is listed under `static_catalogs`, so it is
  never looked up and needs no BROWSE grant.

## Health

`/api/health` returns the environment, the number of live dashboards, any that failed validation (`broken`) and any
switched off for this environment (`hidden`). A broken dashboard is left out of the navigation; the others keep
working. The reason is in the app log. (`/healthz` still works when you run the app locally, but once deployed the
Databricks Apps proxy answers that path itself with an empty page, so use `/api/health`.)

## Review a deployment

Record the revision and active deployment ID after starting the app and before any scheduled stop. Run this
read-only check with the intended workspace profile and a recent Databricks SDK that supports app scan findings.
The caller needs `CAN USE` for the health request and `CAN MANAGE` to read scan findings.

```bash
python scripts/review_app.py --profile <profile> --app <app-name> --env <environment> \
  --deployment <active-deployment-id>
# To confirm a particular finding no longer appears, also pass --tracked-rule <scanner-rule-id>.
```

1. **Health and smoke test.** Confirm the environment and the dashboard count. Open at least one changed
   dashboard with its intended viewer identity and check live data, filters, drill-down and freshness. Record
   first-load and repeat-load times separately for the actions users care about.
2. **Security.** Match the Security tab's code version to the active deployment, and review new and existing
   findings. Unavailable, incomplete, unrecorded and skipped scans have unknown coverage. An empty findings list
   with one of those statuses cannot verify a fix. Record the result and follow up on the next deployment with
   source changes. A tracked finding still counts as detected if it was ignored or marked resolved. Keep a
   source review and regression test for the fix and leave triage decisions to the app owner.
3. **Insights.** Record the time window and traffic alongside availability and service health. In **System
   metrics**, compare requests by HTTP status, p50/p95/p99 latency, CPU versus its limit, and memory versus its
   limit. Where available, show deployment markers to correlate changes with the release. Mark missing series or
   sparse traffic in the review. Keep personal viewer details and raw workspace metrics out of the public repo.

| Observation | Recommended follow-up |
|---|---|
| First loads slow down while CPU and memory have headroom | Compare cold and warm requests. Check warehouse startup, query history and cache or permission probes before changing app compute. |
| CPU stays near its limit at normal traffic | Profile the slow routes and remeasure on representative traffic before resizing. |
| Memory grows toward its limit | Inspect result sizes and in-process caches. Compare working set before and after peak traffic and review cache TTLs and row caps. |
| Unexpected 401/403 or recurring 5xx | Check the affected route and time window. Separate expected identity or access denials from app errors and check runtime logs. |
| App availability dips while service health stays high | Compare incident times with deployments, app starts/stops and runtime logs before assigning a cause. |

The script returns nonzero for unhealthy or unverified deployments, open critical findings, or a present tracked
rule. It reports its health request's HTTP duration. Use the Insights UI for the platform's system metrics and
the dashboard smoke test for user-facing latency. See [Databricks security scanning](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/security-scanning)
and [Databricks Apps monitoring](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/monitor).

## When something goes wrong

| Symptom | Likely cause |
|---|---|
| "Couldn't load this data: … does not have USE CATALOG / SELECT" | The viewer lacks Unity Catalog access to a view. Grant it to their group |
| The sample dashboards say `samples` is not found | The workspace has no `samples` catalog, or an admin has hidden it. Use a workspace that has it (Databricks Free Edition does), or switch the samples off |
| A dashboard is missing from the navigation | The person isn't in its `groups`, it is switched off for this environment, or it failed validation (`/api/health`) |
| App fails to start: `DATABRICKS_HOST=... matches no host` | The workspace host doesn't match `environments:` in `src/environments.yml`. Fix the host or set `PORTAL_ENV` |
| Map tiles don't appear | The network blocks `tile.openstreetmap.org`. The points still plot |
| Deployment fails on "Run every dataset" | A view the SQL uses doesn't exist in that environment's catalog yet, or the deploying service principal can't read it |
| First load of a page is slow | The cache was empty (after a deployment, restart or a scheduled stop), the warehouse was busy, or the views are slow. See [How data refreshes](#how-data-refreshes). Use `cache: shared` with `warm:` if everyone sees the same data, raise `cache_ttl`, or build a pre-aggregated table |
| No "Ask Genie" bar | The dashboard has no Genie space for this environment (see "Ask Genie" above) |
| "You can't use Genie for this dashboard yet" | The person lacks `CAN RUN` on the Genie space. Add them (or their group) in the space's Share dialog |
| "The portal doesn't have your permission to use Genie yet" | The person hasn't consented to the `genie` scope, or the app was deployed without it. Reload the portal; check `user_api_scopes` in `resources/portal.app.yml` |
| "Genie couldn't answer that. … INSUFFICIENT_PERMISSIONS …" | The person can use the space but lacks `SELECT` on a view it reads. Grant it in Unity Catalog |
| "Genie is busy. Try again in a minute." | Genie's per-workspace question limit was reached (HTTP 429) |
| Genie's numbers differ from the dashboard | The space reads different views or rules from the dashboard. Compare its SQL (Show SQL) with the dashboard's `sql/` files, and fix the space or the `about` text |


## Shared-result access and startup policy

Every shared user-auth dataset checks the full bound query as the reader with LIMIT 0, even on a result-cache hit
or refresh. Allowed checks last 30 minutes, denied checks 5 minutes. Revoked grants may take 30 minutes to
be reflected, and new grants up to 5 minutes; source-read failures return 403, and unavailable checks return 502 without cached rows. `auth: app`
remains the explicit service-principal mode. Use per-viewer caching for viewer-specific row filters or masks.
A decision covers every filter value: changing a filter does not run another check, unless the parameter is used
inside `IDENTIFIER(...)` or a table function that reads by name or path. `TABLE_OR_VIEW_NOT_FOUND`,
`SCHEMA_NOT_FOUND` and `CATALOG_NOT_FOUND` count as denials (Unity Catalog hides objects a reader can't see), so a
newly granted reader may wait up to a minute. See decision 0013.

Set `warm_at: startup` beside a dataset's `warm:` list to preload only once per process. It still requires warming
to be enabled for that environment (`warm.environments`), and local scripts still disable background warming.
The default `warm_at: schedule` retains startup plus weekday scheduled runs. Expiry and Refresh still run queries.

The freshness panel puts changed managed tables first, newest first, with counts, a text tag and how long after
your data each was written; unchanged tables follow, newest first; live and untracked sources come last, ordered
by kind (live, external, static, unknown, none). It opens changed details automatically and remembers manual open/closed choices.
Optional `data_through` names a DATE result column and shows the latest returned event day. The fetch time,
source-write time and event coverage are different facts. Missing coverage is never replaced with today's date.
