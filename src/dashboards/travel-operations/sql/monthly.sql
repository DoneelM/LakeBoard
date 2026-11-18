-- Check-in month, not payment or booking-created month. Keep destination grain for browser filters.
SELECT p.destination_id, DATE_FORMAT(b.check_in, 'yyyy-MM') AS month,
       COUNT(*) AS bookings, COUNT_IF(b.status = 'cancelled') AS cancelled,
       SUM(CASE WHEN b.status <> 'cancelled' THEN b.total_amount ELSE 0 END) AS booked_value
FROM samples.wanderbricks.bookings b
JOIN samples.wanderbricks.properties p ON p.property_id = b.property_id
WHERE YEAR(b.check_in) = :year
GROUP BY p.destination_id, DATE_FORMAT(b.check_in, 'yyyy-MM')
ORDER BY month, p.destination_id
