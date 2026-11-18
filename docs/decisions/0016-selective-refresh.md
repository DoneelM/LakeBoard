# 0016. Selective refresh and query profiling

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

The portal used to bypass the result cache for every loaded dataset on each press of Refresh data.
Datasets with overlapping inputs and fixed samples could repeat warehouse work without changing the output.

## Decision

- Use an on-demand metadata check for loaded datasets. Check a distinct directly referenced source once and
  compare its change time with each dependent result's SQL start time. Treat fixed catalogs as immutable.
- Revalidate an unchanged result through the usual data route. Retain its access checks, cache key and TTL.
  Return 304 when the server can reuse the same result. Provide Refresh all to force the loaded queries.
- Rerun on missing or uncertain metadata, views, external or federated inputs and recognized changing expressions
  or relative defaults. Authors set `refresh: always` when a dataset has dependencies outside its source writes,
  such as a custom function or policy whose inputs can change independently.
- Log statement IDs and app-observed elapsed time for dataset queries so operators can find comparable
  executions in Databricks Query Profile.

## Limitations

Direct managed Delta tables use Unity Catalog modification timestamps. Metadata checks have a bounded time
and observe a point in time. View dependencies from the deploy-time map are useful for the freshness panel,
but cannot establish that a view's definition or hidden inputs are unchanged. The selective check does not
make incremental edits to cached rows. A changed input reruns its dependent query.
