# World Weather (sample)

A sample dashboard over `samples.accuweather`, AccuWeather data published on the Databricks Marketplace and included
in the `samples` catalog. It shows a map coloured by a value, a custom d3 chart, and observed data joined to a forecast.

## What it shows

- **KPI tiles** for the chosen city: average temperature, hottest day, coldest night, precipitation and wet days,
  hours of sunshine and peak UV, and the forecast average against the observed one.
- **Map** of 50 cities coloured by average observed temperature (sky blue cold, slate mild, amber warm, red hot).
  Clicking a city picks it.
- **Day by day** for the chosen city: the daily low-to-high band, the daily average and precipitation bars, with the
  forecast days shaded.
- **Hottest, wettest and sunniest cities** and a table of all 50 (sortable, CSV; clicking a row picks the city).
- **Filter**: city, sent to SQL. The default is Sydney.

## Data

`samples.accuweather`, metric tables: `historical_daily_calendar_metric` (50 cities, 27 June to 12 July 2024, 800 rows)
and `forecast_daily_calendar_metric` (12 to 26 July 2024, 750 rows). Degrees Celsius, millimetres, hours. The day by
day view shows observed days, then forecast days after the last observed one. City names are stored in lower case;
the page shows them in title case.

| Dataset | SQL | Rows | Parameters |
|---|---|---|---|
| `cities` | `sql/cities.sql` | 50 | none |
| `daily` | `sql/daily.sql` | 30 | `city` |

## How the numbers were checked

Against direct queries: 50 distinct cities in 43 countries; Baghdad has the highest observed average (38.2 °C) and
Riyadh the next (36.7 °C); Sydney returns 16 observed and 14 forecast days.
