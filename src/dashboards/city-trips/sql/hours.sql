-- Trips by weekday (0 = Monday … 6 = Sunday) and hour of pickup, for the heatmap. At most 168 rows.
SELECT
  weekday(tpep_pickup_datetime) AS weekday,
  hour(tpep_pickup_datetime)    AS hour,
  COUNT(*)                      AS trips
FROM samples.nyctaxi.trips
WHERE tpep_pickup_datetime >= :date_from
  AND tpep_pickup_datetime < date_add(:date_to, 1)
GROUP BY 1, 2
