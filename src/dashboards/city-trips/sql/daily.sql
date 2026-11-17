-- One row per pickup day: the trip count and the day's totals.
-- The page adds the days up for the tiles and divides totals by trips for the averages.
SELECT
  DATE(tpep_pickup_datetime)                                                          AS day,
  COUNT(*)                                                                            AS trips,
  ROUND(SUM(fare_amount), 2)                                                          AS fares,
  ROUND(SUM(trip_distance), 1)                                                        AS miles,
  ROUND(SUM(timestampdiff(SECOND, tpep_pickup_datetime, tpep_dropoff_datetime)) / 60, 1) AS minutes
FROM samples.nyctaxi.trips
WHERE tpep_pickup_datetime >= :date_from
  AND tpep_pickup_datetime < date_add(:date_to, 1)   -- date_to is inclusive
GROUP BY 1
ORDER BY 1
