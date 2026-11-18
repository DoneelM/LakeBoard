-- Load only after a destination is selected. Never read guest or host contact details.
WITH bookings AS (
  SELECT property_id, COUNT(*) AS bookings, COUNT_IF(status = 'cancelled') AS cancelled,
         SUM(CASE WHEN status <> 'cancelled' THEN total_amount ELSE 0 END) AS booked_value
  FROM samples.wanderbricks.bookings
  WHERE YEAR(check_in) = :year
  GROUP BY property_id
), reviews AS (
  SELECT property_id, COUNT(*) AS reviews, AVG(rating) AS rating
  FROM samples.wanderbricks.reviews
  WHERE NOT is_deleted AND YEAR(created_at) = :year
  GROUP BY property_id
)
SELECT p.property_id, p.title, p.property_type, p.bedrooms, p.max_guests,
       COALESCE(b.bookings, 0) AS bookings, COALESCE(b.cancelled, 0) AS cancelled,
       COALESCE(b.booked_value, 0) AS booked_value, COALESCE(r.reviews, 0) AS reviews, r.rating
FROM samples.wanderbricks.properties p
LEFT JOIN bookings b ON b.property_id = p.property_id
LEFT JOIN reviews r ON r.property_id = p.property_id
WHERE p.destination_id = :destination_id
ORDER BY booked_value DESC
