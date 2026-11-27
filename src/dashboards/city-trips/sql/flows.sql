-- Where trips go: trips, fares and miles from each pickup area to each dropoff area. At most 81 rows.
-- Areas come from the ZIP code: the three airports by their own ZIP (JFK 11430, LaGuardia 11371, Newark 07114),
-- then the borough by ZIP range. ZIP ranges follow borough lines closely but not exactly; anything else is
-- "Outside NYC".
WITH t AS (
  SELECT fare_amount, trip_distance,
    CASE WHEN pickup_zip = 11430 THEN 'JFK' WHEN pickup_zip = 11371 THEN 'LaGuardia' WHEN pickup_zip = 7114 THEN 'Newark'
         WHEN pickup_zip BETWEEN 10000 AND 10299 THEN 'Manhattan' WHEN pickup_zip BETWEEN 10300 AND 10399 THEN 'Staten Island'
         WHEN pickup_zip BETWEEN 10400 AND 10499 THEN 'Bronx' WHEN pickup_zip BETWEEN 11200 AND 11299 THEN 'Brooklyn'
         WHEN pickup_zip IN (11004, 11005) OR pickup_zip BETWEEN 11100 AND 11199 OR pickup_zip BETWEEN 11350 AND 11499 OR pickup_zip BETWEEN 11690 AND 11699 THEN 'Queens' ELSE 'Outside NYC' END AS from_area,
    CASE WHEN dropoff_zip = 11430 THEN 'JFK' WHEN dropoff_zip = 11371 THEN 'LaGuardia' WHEN dropoff_zip = 7114 THEN 'Newark'
         WHEN dropoff_zip BETWEEN 10000 AND 10299 THEN 'Manhattan' WHEN dropoff_zip BETWEEN 10300 AND 10399 THEN 'Staten Island'
         WHEN dropoff_zip BETWEEN 10400 AND 10499 THEN 'Bronx' WHEN dropoff_zip BETWEEN 11200 AND 11299 THEN 'Brooklyn'
         WHEN dropoff_zip IN (11004, 11005) OR dropoff_zip BETWEEN 11100 AND 11199 OR dropoff_zip BETWEEN 11350 AND 11499 OR dropoff_zip BETWEEN 11690 AND 11699 THEN 'Queens' ELSE 'Outside NYC' END AS to_area
  FROM samples.nyctaxi.trips
  WHERE tpep_pickup_datetime >= :date_from
    AND tpep_pickup_datetime < date_add(:date_to, 1)
)
SELECT from_area, to_area, COUNT(*) AS trips, ROUND(SUM(fare_amount), 2) AS fares, ROUND(SUM(trip_distance), 1) AS miles
FROM t
GROUP BY 1, 2
ORDER BY 3 DESC
