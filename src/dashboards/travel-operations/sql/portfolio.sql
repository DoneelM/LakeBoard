-- Aggregate each fact separately, then join at destination grain. Booking value includes pending,
-- confirmed and completed bookings, excludes cancelled, and is not recognized revenue or settled cash.
WITH inventory AS (
  SELECT destination_id, COUNT(*) AS properties, AVG(property_latitude) AS lat,
         AVG(property_longitude) AS lon
  FROM samples.wanderbricks.properties
  GROUP BY destination_id
), bookings AS (
  SELECT p.destination_id, COUNT(*) AS bookings,
         COUNT_IF(b.status = 'cancelled') AS cancelled,
         COUNT_IF(b.status = 'pending') AS pending,
         SUM(CASE WHEN b.status <> 'cancelled' THEN b.total_amount ELSE 0 END) AS booked_value,
         MAX(b.check_in) AS last_check_in
  FROM samples.wanderbricks.bookings b
  JOIN samples.wanderbricks.properties p ON p.property_id = b.property_id
  WHERE YEAR(b.check_in) = :year
  GROUP BY p.destination_id
), reviews AS (
  SELECT p.destination_id, COUNT(*) AS reviews, SUM(r.rating) AS rating_sum,
         COUNT_IF(r.rating < 2.5) AS low_reviews, MAX(TO_DATE(r.created_at)) AS last_review
  FROM samples.wanderbricks.reviews r
  JOIN samples.wanderbricks.properties p ON p.property_id = r.property_id
  WHERE NOT r.is_deleted AND YEAR(r.created_at) = :year
  GROUP BY p.destination_id
)
SELECT d.destination_id, d.destination, d.country, i.lat, i.lon, i.properties,
       COALESCE(b.bookings, 0) AS bookings, COALESCE(b.cancelled, 0) AS cancelled,
       COALESCE(b.pending, 0) AS pending, COALESCE(b.booked_value, 0) AS booked_value,
       b.last_check_in, COALESCE(r.reviews, 0) AS reviews,
       COALESCE(r.rating_sum, 0) AS rating_sum, COALESCE(r.low_reviews, 0) AS low_reviews, r.last_review
FROM samples.wanderbricks.destinations d
JOIN inventory i ON i.destination_id = d.destination_id
LEFT JOIN bookings b ON b.destination_id = d.destination_id
LEFT JOIN reviews r ON r.destination_id = d.destination_id
ORDER BY booked_value DESC
