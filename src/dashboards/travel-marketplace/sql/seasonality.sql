-- Bookings per property type and check-in month of the year (1 to 12), for the seasonality heatmap.
-- Not filtered by property type: every type is a row of the heatmap.
SELECT
  p.property_type,
  MONTH(b.check_in) AS month_of_year,
  COUNT(*)          AS bookings
FROM samples.wanderbricks.bookings AS b
JOIN samples.wanderbricks.properties AS p ON p.property_id = b.property_id
WHERE :destination_id IS NULL OR p.destination_id = :destination_id
GROUP BY p.property_type, MONTH(b.check_in)
ORDER BY p.property_type, month_of_year
