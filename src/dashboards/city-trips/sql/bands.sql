-- How fares spread within each trip-distance band: trip count and fare percentiles. 5 rows.
WITH banded AS (
  SELECT
    fare_amount,
    CASE WHEN trip_distance < 1 THEN 1 WHEN trip_distance < 2 THEN 2 WHEN trip_distance < 5 THEN 3
         WHEN trip_distance < 10 THEN 4 ELSE 5 END AS band_order
  FROM samples.nyctaxi.trips
  WHERE tpep_pickup_datetime >= :date_from AND tpep_pickup_datetime < date_add(:date_to, 1)
)
SELECT
  band_order,
  CASE band_order WHEN 1 THEN 'Under 1 mi' WHEN 2 THEN '1–2 mi' WHEN 3 THEN '2–5 mi'
                  WHEN 4 THEN '5–10 mi' ELSE '10 mi or more' END AS band,
  COUNT(*)                               AS trips,
  percentile_approx(fare_amount, 0.10)   AS p10,
  percentile_approx(fare_amount, 0.25)   AS p25,
  percentile_approx(fare_amount, 0.50)   AS median,
  percentile_approx(fare_amount, 0.75)   AS p75,
  percentile_approx(fare_amount, 0.90)   AS p90
FROM banded
GROUP BY band_order
ORDER BY band_order
