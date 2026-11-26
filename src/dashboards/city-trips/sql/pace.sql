-- How fast taxis move by hour of pickup, weekdays against weekends: miles and hours driven. The page divides
-- miles by hours for the average speed. 48 rows. Trips under a minute or over three hours, and trips under 0.1 or
-- over 100 miles, are left out: they are meter errors in the sample, not driving.
SELECT
  hour(tpep_pickup_datetime)                                                          AS hour,
  CASE WHEN weekday(tpep_pickup_datetime) < 5 THEN 'weekday' ELSE 'weekend' END       AS part,
  COUNT(*)                                                                            AS trips,
  ROUND(SUM(trip_distance), 1)                                                        AS miles,
  ROUND(SUM(timestampdiff(SECOND, tpep_pickup_datetime, tpep_dropoff_datetime)) / 3600, 2) AS hours
FROM samples.nyctaxi.trips
WHERE tpep_pickup_datetime >= :date_from
  AND tpep_pickup_datetime < date_add(:date_to, 1)
  AND timestampdiff(SECOND, tpep_pickup_datetime, tpep_dropoff_datetime) BETWEEN 60 AND 10800
  AND trip_distance BETWEEN 0.1 AND 100
GROUP BY 1, 2
ORDER BY 2, 1
