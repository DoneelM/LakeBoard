-- Bookings and booking value per status (pending, confirmed, completed, cancelled).
SELECT
  b.status,
  COUNT(*)            AS bookings,
  SUM(b.total_amount) AS value
FROM samples.wanderbricks.bookings AS b
JOIN samples.wanderbricks.properties AS p ON p.property_id = b.property_id
WHERE (:destination_id IS NULL OR p.destination_id = :destination_id)
  AND (:property_type IS NULL OR p.property_type = :property_type)
GROUP BY b.status
ORDER BY bookings DESC
