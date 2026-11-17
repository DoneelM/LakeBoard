-- Observed days, then forecast days after the last observed one, for one city. Metric units.
WITH obs AS (
  SELECT
    h.date,
    'observed'                     AS kind,
    h.temperature_min              AS temp_min,
    h.temperature_max              AS temp_max,
    h.temperature_avg              AS temp_avg,
    h.precipitation_lwe_total      AS rain_mm,
    h.minutes_of_sun_total / 60    AS sun_hours,
    h.index_uv_max                 AS uv_max,
    h.humidity_relative_avg        AS humidity,
    CAST(NULL AS DOUBLE)           AS rain_chance
  FROM samples.accuweather.historical_daily_calendar_metric AS h
  WHERE h.city_name = :city
)
SELECT * FROM obs
UNION ALL
SELECT
  f.date,
  'forecast',
  f.temperature_min,
  f.temperature_max,
  f.temperature_avg,
  f.precipitation_lwe_total,
  f.minutes_of_sun_total / 60,
  f.index_uv_max,
  f.humidity_relative_avg,
  CAST(f.precipitation_probability AS DOUBLE)
FROM samples.accuweather.forecast_daily_calendar_metric AS f
WHERE f.city_name = :city
  AND f.date > (SELECT MAX(date) FROM obs)
ORDER BY date
