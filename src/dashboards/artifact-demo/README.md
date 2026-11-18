# Artifact Demo

A sample page written the way a Claude Dashboard artifact is, running in the portal unchanged
(`page: artifact`, decision [0011](../../../docs/decisions/0011-claude-dashboard-artifacts.md)). It reads only the
built-in `samples` catalog, so it runs in any workspace.

## What it shows

| Part of the page | Source | What it holds |
|---|---|---|
| Region picker (`<select class="dash-select">`) | `yearly` | The five regions, plus "All regions". Kept in `dash.params().region` and the link |
| Tiles: revenue, orders, average order, years | `yearly` | Order revenue and count per region and year (30 rows) |
| Revenue by year (lines) | `yearly` | Same rows; the selected region is drawn in colour |
| Revenue by market segment (bars) | `segment_mix` (a `dash.calc`) | `segments` filtered to the selected region and summed per segment |
| Year by year (table, hidden until opened) | `yearly` | Same rows, one row per region |

## Data source

`samples.tpch` (orders, customer, nation, region): orders dated 1992 to 1997. The sample's orders stop in
August 1998, so 1998 is left out rather than shown as a fall. Revenue is the sum of `o_totalprice`. The data never
changes.

## What it demonstrates

- `<meta name="dash-one-writer">`, `<link href="theme.css">` and `<script src="charts.js">` by bare name. The files
  live in `assets/` and are served from `/d/artifact-demo/assets/`.
- Two scripts that both declare `const fmt`: each runs in its own scope; `charts.js` shares `window.AdCharts`.
- `dash.draw(name, fn)` drawings, one `dash.draw(name, {mount, update, unmount})` (the picker), a drawing under a
  `hidden` section that only runs once it is shown, and one `dash.calc` that reruns when the region changes.
- `data-source` marks, which get `data-dash-source-state` while data loads.
- Only the design tokens an artifact can rely on (`--color-*`, `--cds-*`, `--font-anthropic-sans`).

## How the numbers were checked

Both queries were run read-only against the dev workspace: `yearly` returns 30 rows (5 regions x 6 years) and
`segments` 25 rows (5 regions x 5 segments).
