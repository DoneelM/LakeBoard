-- One row per city: where it is and how its weather was over the observed days, plus the forecast average.
-- Metric units: degrees Celsius, millimetres of precipitation, hours of sunshine.
WITH obs AS (
  SELECT
    h.city_name,
    MAX(h.country_code)              AS country_code,
    AVG(h.latitude)                  AS lat,
    AVG(h.longitude)                 AS lon,
    AVG(h.temperature_avg)           AS temp_avg,
    MAX(h.temperature_max)           AS temp_max,
    MIN(h.temperature_min)           AS temp_min,
    SUM(h.precipitation_lwe_total)   AS rain_mm,
    COUNT_IF(h.has_precipitation)    AS wet_days,
    SUM(h.minutes_of_sun_total) / 60 AS sun_hours,
    MAX(h.index_uv_max)              AS uv_max,
    AVG(h.humidity_relative_avg)     AS humidity,
    COUNT(*)                         AS days
  FROM samples.accuweather.historical_daily_calendar_metric AS h
  GROUP BY h.city_name
),
fc AS (
  SELECT
    f.city_name,
    AVG(f.temperature_avg)          AS fc_temp_avg,
    MAX(f.temperature_max)          AS fc_temp_max,
    SUM(f.precipitation_lwe_total)  AS fc_rain_mm,
    MAX(f.precipitation_probability) AS fc_rain_chance
  FROM samples.accuweather.forecast_daily_calendar_metric AS f
  GROUP BY f.city_name
)
SELECT
  obs.city_name AS city,
  INITCAP(obs.city_name) AS name,
  UPPER(obs.country_code) AS country_code,
  obs.lat, obs.lon,
  obs.temp_avg, obs.temp_max, obs.temp_min,
  obs.rain_mm, obs.wet_days, obs.sun_hours, obs.uv_max, obs.humidity, obs.days,
  fc.fc_temp_avg, fc.fc_temp_max, fc.fc_rain_mm, fc.fc_rain_chance
FROM obs
LEFT JOIN fc ON fc.city_name = obs.city_name
ORDER BY obs.temp_avg DESC
