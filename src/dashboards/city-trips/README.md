# City Trips

The flagship sample: New York City taxi trips in January and February 2016, and the weekend a blizzard stopped
the city. It is the worked example in [docs/AUTHORING.md](../../../docs/AUTHORING.md) and runs in any Databricks
workspace, because it reads only the built-in `samples` catalog.

## The stories in the data

Every headline on the page is worked out from the rows on screen, so it stays true for any dates picked. With the
whole sample (checked against the dev workspace on 26 Nov 2026):

- **The blizzard.** Saturday 23 Jan 2016 had 78 trips against 414 on a normal Saturday (−81%). Not one trip was
  recorded for 14 hours, 5 pm Saturday to 7 am Sunday; Sunday was −53% and Monday −21%. This matches Winter Storm
  Jonas and New York's road travel ban (2:30 pm Saturday to 7 am Sunday). The storm's name and the ban times are
  the only facts on the page that don't come from the data; they are in `EVENTS` in `index.html` and shown only
  when the data shows that day as unusual.
- **Rush hour halves the city's speed.** Weekdays: about 23 mph at 4 to 5 am, 10 mph at 9 am.
- **Manhattan is the system.** 18,637 of 21,932 trips (85%) start and end there.
- **Airport runs.** 3.4% of trips, 8.9% of fares: $32.88 on average against $11.64.
- **Weekend nights.** 1 to 4 am is about 3× busier per day on Saturday and Sunday than on weekdays.

When the dates picked have no unusual day (February, say), the headline switches to the rush-hour pattern.

## What it shows

| Part of the page | Dataset | What it holds |
|---|---|---|
| Headline (`kit.insight`) | `daily`, `hourly`, `pace` | The most unusual day against a normal one, or the rush-hour pattern |
| Tiles with trends | `daily`, `pace`, `flows` | Trips, fares, average fare, average speed, Manhattan share |
| Trips per day against a normal day | `daily`, `hourly` | Each day, the middle half of the sample's days for that weekday (shaded) and unusual days marked |
| The storm (or the last week picked), hour by hour | `hourly` | Trips per hour against a normal hour for that weekday and time; the travel ban shaded |
| How fast the city moves | `pace` | Average speed per pickup hour, weekdays and weekends |
| When the city rides (heatmap) | `hours`, `daily` | Trips per weekday and hour; busiest hour outlined; weekend nights |
| Busiest ZIP codes | `zips` | Top 10 pickups or dropoffs, with the neighbourhood for well-known ZIP codes |
| Where trips go (flows) | `flows` | Trips between areas; the biggest flows outside Manhattan below |
| Airport runs | `flows` | Share of trips against share of fares, average fares, each airport |
| Fares by distance | `bands` | Fare percentiles for five distance bands |
| Day by day (table, CSV) | `daily`, `hourly` | Every day with its difference from a normal day |

`hourly` has no date filter on purpose: it is the page's baseline (what a normal day and hour look like), so even a
one-week range is compared with the whole sample. Averages are worked out from totals, not as averages of averages.

## Data source

`samples.nyctaxi.trips`: 21,932 trips, pickups from 1 Jan to 29 Feb 2016, in New York local time. Columns used:
pickup and dropoff time, trip distance (miles), fare amount (USD) and pickup and dropoff ZIP code. The data never
changes.

Known quirks, left in as they are in the source and called out where they matter:

- 33 trips last more than three hours (one nearly a full day); 10 trips have a fare of zero or less. The speed
  chart and tile leave out trips under a minute or over three hours and under 0.1 or over 100 miles.
- **JFK barely appears**: 11 trips, against 698 for LaGuardia. Real New York traffic has far more JFK trips; this
  is how the sample was built. The airport card says so.
- Areas come from ZIP ranges, which follow borough lines closely but not exactly.

## What it demonstrates

- **A headline from the data** (`kit.insight`) and card titles that state the finding ("Rush hour halves the
  city's speed"), each worked out from the rows on screen.
- **A baseline dataset** without filters, so any date range is compared with normal.
- **`kit.line` options**: a normal range (`band`), labelled events (`marks`), a shaded closure (`spans`), hourly
  and numeric axes, hover tooltips.
- **Tiles with trends** (`spark`) and numbers that count up.
- **Custom d3 charts** (heatmap, flows, fare ranges) with `kit.tip` tooltips, in the kit's style.
- **SQL parameters** with fixed defaults and date presets; **shared cache** and **warming** at startup.

## Checks

Each query was run read-only against the dev workspace on 26 Nov 2026 for the default range, 1 Jan to 29 Feb 2016:

| Dataset | Rows | Check |
|---|---|---|
| `daily` | 60 | Trips add up to 21,932, the row count of the table; fares $270,832.28 |
| `hours` | 168 | Trips add up to 21,932; busiest slot Thursday 18:00 (230 trips) |
| `zips` | 20 | 10 pickup and 10 dropoff; 10001 is busiest both ways (1,227 pickups, 1,069 dropoffs) |
| `bands` | 5 | Trips add up to 21,932; median fare rises from $5.00 (under 1 mi) to $43.50 (10 mi or more) |
| `hourly` | 1,414 | 1,440 hours less 26 with no trips (14 of them in the storm); trips add up to 21,932 |
| `pace` | 48 | 24 hours × weekday and weekend; weekday speed 23.3 mph at 4 am, 10.0 mph at 9 am |
| `flows` | 35 | Trips add up to 21,932; Manhattan to Manhattan 18,637 |

Default warmed datasets use `warm_at: startup`: once per process, in configured warm environments. Expiry and manual
Refresh still run queries.
