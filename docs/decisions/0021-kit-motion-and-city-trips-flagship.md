# 0021. Dashboards that lead with a finding: kit upgrade, City Trips flagship, TPC-H samples removed

- **Status:** Accepted
- **Date:** 2026-11-26
- **Links:** pull request "Dashboards that lead with a finding"

## Context
The sample dashboards looked alike and said little: tiles, a line, some bars. Two of them, Artifact Demo and Sales &
Margin, read `samples.tpch`, whose values are spread evenly: every region within about 2% of the others, every ship
mode and order priority identical to 0.1% (63.2% of lines late, 15.5 days in transit). No design makes a flat line
worth looking at. A read-only survey of the `samples` catalog found one dataset with real events, `nyctaxi` (the
January 2016 blizzard, rush-hour speed), and shape in `tpcds_sf1` (seasonality, geography); `wanderbricks` funnel
tables and `tpch` are uniform.

## Decision
- **Kit** (`src/static/kit.js`, `kit.css`), for every dashboard: tile numbers count up when they change, tiles take
  `spark` and `delta`; `kit.line` adds an area under one line, hover tooltips, draw-in, `band`, `marks`, `spans`,
  hourly and numeric axes and `tip`; bars grow from their last length; new `kit.tip` and `kit.insight`; cards and
  new tiles rise in once. Motion runs only when values change (never on a resize redraw) and never under
  `prefers-reduced-motion`. Existing calls keep working unchanged.
- **City Trips** is the flagship: a headline worked out from the data (`kit.insight`), card titles that state the
  finding, three new datasets (`hourly` as an unfiltered baseline, `pace`, `flows`), the blizzard hour by hour
  with the travel ban, speed by hour, flows between areas, airport runs and date presets.
- **Removed** `src/dashboards/artifact-demo/` and `src/dashboards/sales-margin/` (TPC-H). The e2e smoke test opens
  City Trips instead.

## Why
- One change to the kit lifts all seven dashboards; pages don't each hand-roll motion and tooltips.
- A dashboard impresses when it says something true. City Trips' headline and titles come from the rows on
  screen, so they stay true for any dates picked.
- Removing flat dashboards is better than decorating them.

## Limitations
- The storm's name and the ban times are facts from outside the data, kept in `EVENTS` in City Trips' page and
  shown only when the data shows the day as unusual.
- `hourly` ignores the date filter (by design), so it is 1,440 rows at most rather than the dates picked.
- No live example of a `page: artifact` dashboard remains; the runtime is still tested (decision 0011, update).
- Count-up parses the number out of the formatted text; a value with two numbers or a word before the number
  ("1992–1997", "Jan 2016") is shown without counting.
- `samples.nyctaxi` has almost no JFK trips (11 against 698 at LaGuardia); the page says so instead of hiding it.

## Alternatives considered
- Re-point the TPC-H pages at `tpcds_sf1`: it has seasonality and geography, but its margins (−48% in every
  category), promotions and return reasons are noise, and Omnichannel Retail already tells its story.
- Redesign every page now: larger to review against `src/reviewed_pages.yml`; the kit upgrade already reaches them.
- A charting library (ECharts, Plotly): another dependency to vendor and pin, against a d3 kit that already fits
  the theme and the Content-Security-Policy.

## Changing it later
Motion: `still()` in `kit.js`. The baseline: `hourly` in `src/dashboards/city-trips/dashboard.yml`. Events:
`EVENTS` in `src/dashboards/city-trips/index.html`.

## Links
`src/static/kit.js`; `src/static/kit.css`; `src/dashboards/city-trips/`; `docs/AUTHORING.md` (kit table);
`e2e/test_smoke.py`; decision 0011.
