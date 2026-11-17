# Travel Marketplace (sample)

A sample dashboard over `samples.wanderbricks`, the holiday-rental marketplace that ships with Databricks. It shows
a map that drills from 42 destinations down to each property, and joins five tables in SQL.

## What it shows

- **KPI tiles**: revenue (bookings not cancelled), bookings, average nightly rate (revenue per night booked),
  cancellation rate, guest rating (weighted by reviews) and properties with their average base price.
- **Map**: one circle per destination, sized by revenue, at the centre of its properties. Clicking a circle, a row
  of the league table or the Destination filter picks a destination; the map then shows each of its properties,
  coloured by property type.
- **Top destinations by revenue**, **revenue by check-in month**, a **seasonality heatmap** (each property type's
  bookings by month of the year: ski resorts peak in winter, summer getaways in June and July), **booking status**
  and **cancellation rate by destination** (destinations with 50 bookings or more).
- **Destination league table** (sortable, CSV) and, once a destination is picked, its **properties** (top 200).
- **Filters**: destination and property type, both sent to SQL.

## Data

`samples.wanderbricks`: 72,247 bookings (check-in from December 2022 to July 2025), 18,163 properties, 42 destinations,
99,317 reviews that aren't deleted. Revenue is `total_amount` of bookings that weren't cancelled; nights are check-out
minus check-in. The sample has only a handful of bookings before June 2023, so the monthly trend starts there, and
bookings grow sharply in mid-2025. Host and guest contact details are never read.

| Dataset | SQL | Rows | Parameters |
|---|---|---|---|
| `destinations` | `sql/destinations.sql` | 42 | `property_type` |
| `monthly` | `sql/monthly.sql` | 26 | `destination_id`, `property_type` |
| `seasonality` | `sql/seasonality.sql` | up to 48 | `destination_id` |
| `status` | `sql/status.sql` | 4 | `destination_id`, `property_type` |
| `properties` | `sql/properties.sql` | up to 1,788 (Phuket) | `destination_id`, `property_type` |

## How the numbers were checked

Against direct queries on the sample (all destinations, all types): 72,247 bookings (`COUNT(*)` of `bookings`);
status split pending 31,575, confirmed 17,948, cancelled 15,285, completed 7,439; 18,163 properties; Phuket has the
most properties (1,788). The tiles and the league table show the same figures.
