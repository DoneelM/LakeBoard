-- The 10 busiest pickup ZIP codes and the 10 busiest dropoff ZIP codes. 20 rows.
WITH by_zip AS (
  SELECT 'pickup' AS direction, pickup_zip AS zip, COUNT(*) AS trips, ROUND(AVG(fare_amount), 2) AS avg_fare
  FROM samples.nyctaxi.trips
  WHERE tpep_pickup_datetime >= :date_from AND tpep_pickup_datetime < date_add(:date_to, 1)
  GROUP BY pickup_zip
  UNION ALL
  SELECT 'dropoff', dropoff_zip, COUNT(*), ROUND(AVG(fare_amount), 2)
  FROM samples.nyctaxi.trips
  WHERE tpep_pickup_datetime >= :date_from AND tpep_pickup_datetime < date_add(:date_to, 1)
  GROUP BY dropoff_zip
)
SELECT direction, zip, trips, avg_fare
FROM by_zip
QUALIFY row_number() OVER (PARTITION BY direction ORDER BY trips DESC, zip) <= 10
