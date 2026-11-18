# 0003. Caching and warming

- **Status:** Accepted

## Context
Each page loads its datasets once and filters in the browser. Some queries are slow (a query over a federated
source can take minutes). We wanted the next person to get the result at once, without a database or extra
infrastructure.

## Decision
The full behaviour is in [OPERATIONS.md](../OPERATIONS.md) "How data refreshes". In short:
- Results are cached in the app's memory, keyed on dashboard, dataset, who, and the parameter values sent to SQL.
  Each result is reused until its `cache_ttl` (default 1 hour) runs out.
- By default the cache is **per viewer**, because queries run as the viewer (see 0002).
- `cache: shared` keeps one result for everybody, for data every viewer may see.
- `cache: shared` plus `warm:` re-runs listed parameter sets in the background once at start-up and at the times
  set in `src/environments.yml` (07:00 and 13:00 on weekdays by default, in `warm.timezone`, which is UTC unless you
  change it), in prod only, as the app's service principal.
- `auth: app` datasets are shared, and by default re-run in the background every `cache_ttl` minus 5 minutes.
- The **Refresh data** button re-runs the datasets the page has loaded, ignoring the cache.

## Why
- No table, file or service to run. The cache comes with the app.
- Per-viewer caching is the safe default when row filters can give two people different rows.
- Shared caching and warming are opt-in, per dataset, where the data allows it.

## Limitations
- The cache is in memory, so a deployment, a restart or the evening prod stop (see 0005) empties it.
- Per viewer means the same query runs once per person, not once per dashboard.
- Nothing starts the prod app in the morning, so the first person waits for the app and for their queries. Warming
  only runs once the app is up.
- Refresh only re-runs datasets the page has already loaded. For shared datasets it replaces the result for
  everyone.
- `cache: shared` serves one person's result to the next. A mistake in choosing it could show rows to the wrong
  people.

## Alternatives considered
- **A results table in Unity Catalog or Lakebase.** Survives restarts, but adds a table, jobs and grants to run.
- **Shared cache by default.** Fewer queries, but unsafe with row-level security.

## Changing it later
Mode and TTL are per dataset in `dashboard.yml`. Warming times, time zone and environments are in
`src/environments.yml`. A persistent cache would be a new decision record.

## Links
- [OPERATIONS.md](../OPERATIONS.md) "How data refreshes"; [DESIGN.md](../DESIGN.md) "Caching and cost"
- `src/portal/data.py`, `src/environments.yml` (`warm:`), `scripts/grant_app_access.py`


## Change, 18 November 2026: startup-only warming and reader authorization

`warm_at: startup` with a `warm:` parameter list runs once at process startup, in the configured warm environments.
The default `warm_at: schedule` preserves startup plus scheduled runs. It does not make data permanent: expiry,
manual refresh and process restart behave as before. Reader access is checked even for a shared cache hit;
see [0013](0013-platform-reliability.md).
