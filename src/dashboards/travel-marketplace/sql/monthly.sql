-- Bookings, revenue (not cancelled) and cancellations per check-in month. The sample has only a handful of bookings
-- before June 2023, so the trend starts there.
SELECT
  DATE_FORMAT(b.check_in, 'yyyy-MM')                               AS month,
  COUNT(*)                                                         AS bookings,
  SUM(CASE WHEN b.status <> 'cancelled' THEN b.total_amount END)   AS revenue,
  COUNT_IF(b.status = 'cancelled')                                 AS cancelled
FROM samples.wanderbricks.bookings AS b
JOIN samples.wanderbricks.properties AS p ON p.property_id = b.property_id
WHERE b.check_in >= DATE'2023-06-01'
  AND (:destination_id IS NULL OR p.destination_id = :destination_id)
  AND (:property_type IS NULL OR p.property_type = :property_type)
GROUP BY DATE_FORMAT(b.check_in, 'yyyy-MM')
ORDER BY month
