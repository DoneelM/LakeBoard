# City Trips

A sample dashboard: New York City taxi trips in January and February 2016. It is the worked example in
[docs/AUTHORING.md](../../../docs/AUTHORING.md) and runs in any Databricks workspace, because it reads only the
built-in `samples` catalog.

## What it shows

| Part of the page | Dataset | What it holds |
|---|---|---|
| Tiles: trips, fares, average fare, distance and trip time | `daily` | One row per pickup day: trips and the day's total fares, miles and minutes |
| Trips per day (line) | `daily` | Same rows |
| When people ride (heatmap) | `hours` | Trips per weekday and hour of pickup (at most 168 rows) |
| Busiest pickup / dropoff ZIP codes (bars) | `zips` | Top 10 ZIP codes each way, with the average fare (20 rows) |
| Fares by trip distance (range chart) | `bands` | Trips and fare percentiles for five distance bands (5 rows) |
| Day by day (table, CSV download) | `daily` | Same rows, with averages per trip |

Averages are worked out from totals (total fares ÷ trips), not as an average of daily averages.

## Data source

`samples.nyctaxi.trips`: 21,932 trips, pickups from 1 Jan to 29 Feb 2016. Columns used: pickup and dropoff time,
trip distance (miles), fare amount (USD) and pickup and dropoff ZIP code. The data never changes.

Known quirks of the sample data: 33 trips last more than three hours (one nearly a full day), which lifts the
average trip time to about 15 minutes against a median of about 11; 10 trips have a fare of zero or less. They are
left in, as they are in the source.

## What it demonstrates

- **SQL parameters** (`date_from`, `date_to`) with fixed defaults, set from the page with `kit.filters` and
  `dash.setParams`. The data is historic, so the defaults are dates, not `@week_start`.
- **Shared cache** (`cache: shared`, `cache_ttl: 24h`): the sample table is readable by every workspace user and
  has no row-level security, so one result serves everyone.
- **Warming** (`warm:`): the default date range is pre-loaded in the background where warming is switched on.
- **The kit**: `kit.tiles`, `kit.line`, `kit.bars`, `kit.table` with CSV download, `kit.ready` for loading and
  error states, plus two custom d3 charts (heatmap and range chart) drawn in the same style.
- **Small, aggregated queries**: the largest dataset is 168 rows.

## Checks

Each query was run on 17 Nov 2026 for the default range, 1 Jan to 29 Feb 2016 (the sample table is the same in
every workspace):

| Dataset | Rows | Check |
|---|---|---|
| `daily` | 60 | Trips add up to 21,932, the row count of the table; fares $270,832.28 |
| `hours` | 168 | Trips add up to 21,932; busiest slot Thursday 18:00 (230 trips) |
| `zips` | 20 | 10 pickup and 10 dropoff; 10001 is busiest both ways (1,227 pickups, 1,069 dropoffs) |
| `bands` | 5 | Trips add up to 21,932; median fare rises from $5.00 (under 1 mi) to $43.50 (10 mi or more) |

Default warmed datasets use `warm_at: startup`: once per process, in configured warm environments. Expiry and manual Refresh still run queries.
