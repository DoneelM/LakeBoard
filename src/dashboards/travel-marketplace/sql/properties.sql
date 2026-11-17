-- Every property in the picked destination with its bookings, revenue (not cancelled) and rating.
-- Returns nothing until a destination is picked. Host contact details are never read.
WITH bk AS (
  SELECT
    b.property_id,
    COUNT(*)                                                       AS bookings,
    SUM(CASE WHEN b.status <> 'cancelled' THEN b.total_amount END) AS revenue
  FROM samples.wanderbricks.bookings AS b
  GROUP BY b.property_id
),
rv AS (
  SELECT r.property_id, AVG(r.rating) AS rating, COUNT(*) AS reviews
  FROM samples.wanderbricks.reviews AS r
  WHERE NOT r.is_deleted
  GROUP BY r.property_id
)
SELECT
  p.property_id,
  p.title,
  p.property_type,
  p.base_price,
  p.bedrooms,
  p.max_guests,
  p.property_latitude  AS lat,
  p.property_longitude AS lon,
  COALESCE(bk.bookings, 0) AS bookings,
  COALESCE(bk.revenue, 0)  AS revenue,
  rv.rating,
  COALESCE(rv.reviews, 0)  AS reviews
FROM samples.wanderbricks.properties AS p
LEFT JOIN bk ON bk.property_id = p.property_id
LEFT JOIN rv ON rv.property_id = p.property_id
WHERE p.destination_id = :destination_id
  AND (:property_type IS NULL OR p.property_type = :property_type)
ORDER BY revenue DESC
