-- Trips per pickup hour across the whole sample (1 Jan to 29 Feb 2016), at most 1,440 rows. Times are New York
-- local time. Hours with no trips have no row; the page fills them with zero.
-- No date filter on purpose: this is the page's baseline. It gives the hour-by-hour view of any week and the
-- normal number of trips for each weekday and hour, so a short date range can still be compared with normal.
SELECT
  date_format(date_trunc('HOUR', tpep_pickup_datetime), 'yyyy-MM-dd HH:mm') AS hour_start,
  COUNT(*)                                                                AS trips
FROM samples.nyctaxi.trips
GROUP BY 1
ORDER BY 1
