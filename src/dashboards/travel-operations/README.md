# Travel Operations

A personal LakeBoard showcase by Doneel Maran over the fixed public `samples.wanderbricks` data. It is a new
operating view, not a migration of an employer dashboard. It runs as an ordinary LakeBoard dashboard folder and
needs no extra service, API key or app.

## Views and interactions

- **Overview:** six KPIs, a world map, ranked booking value, check-in-month trend and a cancellation watch list.
  Map markers, Explore buttons and table rows select a destination. Scroll-wheel map zoom is disabled so the page
  scrolls normally. The destination select and table provide keyboard alternatives to map clicks.
- **Destinations:** sortable portfolio table with CSV export; a selected destination loads its property performance
  on demand. The property table shows the top 100 listings and exports the full fetched result.
- **Guest experience:** star distribution, most repeated review phrases and destinations ranked by low-rating share
  (at least 20 reviews). Ratings are weighted by review counts, not averages of destination averages.
- **My destinations:** stars and saved chips persist destination ids in this browser's local storage. No rows,
  contact details or credentials are stored. `My destinations only` intersects the saved set with country and
  destination filters. An empty set has an explicit reset action. Storage failures fall back to in-page memory.
- **TV view:** a reversible presentation layout that keeps the current scope, opens Overview and hides navigation
  and filter controls. Exit with the button or Escape. It does not request fullscreen or run an automatic refresh.
- Tabs support Left/Right, Home/End and URL fragments. Reporting year reaches SQL; country, destination and saved
  scope filter destination aggregates in the browser. Only the property query also takes a destination parameter.
- Loading, empty, query-error and truncated-result messages are explicit. Layout and colours follow LakeBoard's
  light/dark theme and work at phone width.

## Definitions

| Measure | Definition |
|---|---|
| Booked value | Sum of `total_amount` for bookings whose status is not cancelled, including pending, confirmed and completed. This is not recognized revenue or settled cash. Amounts use the sample's dollar convention, with no FX conversion. |
| Bookings | Every booking whose check-in year equals the reporting year, including cancellations. |
| Cancellation rate | Cancelled bookings divided by all bookings in the same scope. |
| Guest rating | Sum of undeleted review ratings divided by review count, filtered by review-created year. |
| Low-rating share | Undeleted reviews below 2.5 stars divided by all undeleted reviews. |
| Properties | All listings in the fixed inventory for destinations in scope, regardless of booking/review year. |
| Coverage | Actual latest check-in date returned for destinations in scope; never inferred from today's date. |

Booking aggregates and review aggregates are computed separately before joining at destination or property grain.
Joining the two raw facts would multiply booking values when a booking has multiple reviews. Review-created year
is independent of check-in year; the two measures are not a matched booking cohort. Deleted reviews are excluded.

## Sample limitations

The default year is 2025, a partial sample through 30 July. Booking volume jumps sharply in mid-2025; do not read
that as genuine business growth, a forecast or a live alert. Review comments are generated from a small repeated
phrase set; the dashboard counts those phrases without claiming AI sentiment or inferred causes. Historical
samples retain their static-source explanation. No payment, guest-name or host-contact columns are queried.

All five datasets use shared 24-hour caching because this fixed public sample has identical rows/masks for every
viewer. Nothing is preloaded at app startup; the page queries on demand. No config values or workspace ids belong
in this folder. This dashboard is independent of the platform-reliability PR; its coverage banner is drawn directly
from the result dates.

## Reconciliation

Checked read-only on the built-in sample for reporting year **2025**:

| Check | Result |
|---|---:|
| Destinations | 42 |
| Listing inventory | 18,163 |
| Bookings | 57,816 |
| Cancelled bookings | 12,455 |
| Pending bookings | 25,209 |
| Non-cancelled booked value | 25,158,599.85 sample dollars |
| Undeleted reviews | 92,266 |
| Sum of review ratings | 277,527.4 |
| Weighted rating | 3.0079 / 5 |
| Latest check-in | 2025-07-30 |

Portfolio booking totals equal a direct aggregate of `bookings` for check-in year 2025. Review count and rating
sum equal a direct aggregate of undeleted `reviews` for review-created year 2025. The sum of monthly booked values
equals the portfolio total. Booking amounts are floating point; reconciliation permits under one sample dollar of
summation-order difference, while counts must match exactly. Property drill-down was tested on Phuket.

## Verification

Static manifest/SQL checks, pytest in default and dev environments, and live SQL shape checks. Browser checks
exercise tabs, saving/reloading destinations, saved-scope empty state, property drill-down, CSV, keyboard tabs,
TV view and Escape, year/country filters, light/dark and desktop/390 px layouts. Review captures stay outside git
until the maintainer approves them for public use.
