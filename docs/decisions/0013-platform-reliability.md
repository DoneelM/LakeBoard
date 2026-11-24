# 0013. Shared access, warm policy and honest freshness

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
A shared result can be populated by a different viewer or the service principal. Checking dashboard groups alone
does not prove the next reader can query its sources. Scheduled warming can also rerun fixed samples needlessly,
and a recent fetch time does not establish the period covered by its records.

## Decision
- For shared user-auth datasets, analyze `SELECT * FROM (<complete bound query>) ... LIMIT 0` as the reader before
  fetching any result. This includes column and function access without relying on table-name parsing. The query
  is the already-validated read-only dataset query; filter values remain SDK parameters.
- Cache authorization per viewer, warehouse, SQL and bound parameters. Allow for five minutes; deny for one.
  Bound the cache at 4,096 entries and use fixed-size locks to coalesce concurrent requests. The cache holds no
  credentials or result rows. Permission failures return 403; other failures return a generic 502 and are not
  cached. Neither serves rows. A 403 also clears old browser rows rather than preserving an artifact preview.
- Keep `auth: app`, per-viewer data and local todo snapshots on their existing paths. Shared results still require
  identical rows and masks for every permitted viewer; permission checks do not establish that equivalence.
- Add `warm_at: startup | schedule`, requiring `warm:`. Startup runs once per process; schedule (the default)
  includes startup and configured weekday times. Existing environment and local-warming controls still apply.
- Group and highlight changed managed source tables, preserving manual disclosure choices. Add optional
  `data_through` for a DATE result column; derive the latest date from actual returned rows, never today's date.

## Limitations
- An allowed decision can outlive a grant revocation by five minutes. This is separate from per-viewer result TTLs.
- LIMIT 0 still requires a running warehouse and query analysis, so a first shared request is slower. Wrapping the
  full query prioritizes complete query authorization over cheaper per-table checks. It retrieves no dataset rows.
- Returning an old browser view cannot erase information a person has already seen, downloaded or copied.
- Startup warming is best-effort, not a warehouse/app startup schedule. Failures are logged, and requests can retry.
- `data_through` only describes the returned result. It does not prove every expected event has arrived.

## Alternatives considered
- Table-only probes are cheaper, but a parser can miss dependencies, columns or functions.
- Removing shared caching avoids cross-viewer results but discards the existing opt-in performance feature.
- Constantly refreshing fixed data wastes warehouse activity; startup-only warming is an explicit author choice.

## Changing it later
`portal/access.py` controls authorization TTLs and limits. `portal/registry.py` validates the manifest fields,
`portal/data.py` handles warm policy and dates, and `static/source-groups.js` orders source details.

## Change, 24 November 2026: filter changes and "not found"

- **Decisions no longer depend on filter values.** The remembered decision is keyed by viewer, warehouse, SQL text
  and each parameter's name and type, not its value, so choosing a new filter value reuses the decision instead of
  running another `LIMIT 0` check. This is safe because dataset SQL names its tables in the text and filter values
  are bound SDK parameters: a value can change which rows match, never which objects are analyzed. The exception
  is a parameter inside `IDENTIFIER(...)` or inside a table function that reads by name or path (`read_*`,
  `table_changes`, `event_log`, `cloud_files_state`): those parameters keep their values in the key, because a new
  value can point at a different object. The scan ignores comments and string literals.
- **`*_NOT_FOUND` counts as a denial.** `TABLE_OR_VIEW_NOT_FOUND`, `SCHEMA_NOT_FOUND` and `CATALOG_NOT_FOUND` are
  remembered as denied for the denial period (five minutes, see below) and return 403. Unity Catalog reports an object the
  reader may not see this way, so treating it as an unavailable check (502, retried on every request) repeated a
  warehouse query for an answer that would not change. Other errors are still not remembered.
- **Longer memory: allowed 30 minutes, denied 5 minutes** (was 5 minutes and 1 minute). With decisions no longer
  tied to filter values, each check covers far more requests, and grants change rarely; the shorter times mostly
  added warehouse queries. This replaces the times in the decision above.

Limitations:
- An object that was really dropped also reads as "denied" for five minutes; the dataset's own query would fail anyway.
- The list of name- or path-taking table functions is explicit. A future function that takes an object name as a
  value would need adding to `NAMING_CALL_RE` in `portal/access.py`; the registry already rejects table functions
  after `FROM`/`JOIN`, so such a call could only appear in a comma join or a scalar position.
- A revoked grant can now take up to 30 minutes to take effect for shared results, and a new grant up to 5 minutes
  after a denial. Use per-viewer caching where access must change sooner.
- A malformed filter value no longer fails the access check if an earlier value was allowed; the dataset query
  itself still rejects it.
