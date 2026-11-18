# 0014. Travel Operations as a personal showcase

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
The existing travel samples demonstrate maps and review analysis. A personal portfolio also needs a coherent
operating view that shows how these interactions work together, with clear measure definitions and historical
sample coverage.

## Decision
Build `travel-operations` as a new dashboard folder over only `samples.wanderbricks`, in the existing Travel
section. Keep the original sample dashboards available as smaller examples. Use the existing page kit, bundled
map library and theme; introduce no framework, third-party script or new data object.

Three views share a country/destination scope: Overview, Destinations and Guest experience. Saved destinations
persist numeric ids in this browser only. TV view is a reversible presentation layout, retaining the current
scope with an Escape exit; it does not refresh queries automatically or request fullscreen permission.

Booking and review facts are aggregated separately before they are joined. Bookings use check-in year, reviews
use review-created year, and inventory includes all listings. Booked value includes pending/confirmed stays,
so it is not labelled revenue. Coverage uses actual returned event dates, never the calendar clock.

## Why
- One operating narrative demonstrates SQL modelling, interactions, accessibility and deployment as one folder.
- Browser-local saved ids require no profile storage service or write privileges.
- Fixed public samples make the showcase reproducible without company data, queries, groups or workspace ids.
- The new dashboard is independent of platform reliability changes, so each PR has a focused review.

## Limitations
The 2025 sample is partial and booking volume jumps sharply near its end. Review phrases repeat. There are no
live alerts, forecasts, exchange rates or real business conclusions. Saved destinations are not synced across
devices. The property table displays the first 100 rows; CSV exports the complete fetched result.

## Changing it later
All queries, page logic and definitions are in `src/dashboards/travel-operations/`. Add personal preference storage
or automatic TV rotation only as a separate feature with explicit access and query-cost choices.
