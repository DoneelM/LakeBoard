-- One row per destination: where it is (the centre of its properties), its size and its booking performance.
-- Revenue counts bookings that were not cancelled. Ratings ignore deleted reviews.
WITH props AS (
  SELECT
    p.destination_id,
    COUNT(*)                AS properties,
    AVG(p.base_price)       AS avg_price,
    AVG(p.property_latitude)  AS lat,
    AVG(p.property_longitude) AS lon
  FROM samples.wanderbricks.properties AS p
  WHERE :property_type IS NULL OR p.property_type = :property_type
  GROUP BY p.destination_id
),
bk AS (
  SELECT
    p.destination_id,
    COUNT(*)                                                         AS bookings,
    SUM(CASE WHEN b.status <> 'cancelled' THEN b.total_amount END)   AS revenue,
    COUNT_IF(b.status = 'cancelled')                                 AS cancelled,
    SUM(CASE WHEN b.status <> 'cancelled' THEN DATEDIFF(b.check_out, b.check_in) END) AS nights
  FROM samples.wanderbricks.bookings AS b
  JOIN samples.wanderbricks.properties AS p ON p.property_id = b.property_id
  WHERE :property_type IS NULL OR p.property_type = :property_type
  GROUP BY p.destination_id
),
rv AS (
  SELECT p.destination_id, AVG(r.rating) AS rating, COUNT(*) AS reviews
  FROM samples.wanderbricks.reviews AS r
  JOIN samples.wanderbricks.properties AS p ON p.property_id = r.property_id
  WHERE NOT r.is_deleted AND (:property_type IS NULL OR p.property_type = :property_type)
  GROUP BY p.destination_id
)
SELECT
  d.destination_id,
  d.destination,
  d.country,
  props.lat,
  props.lon,
  props.properties,
  props.avg_price,
  COALESCE(bk.bookings, 0)  AS bookings,
  COALESCE(bk.revenue, 0)   AS revenue,
  COALESCE(bk.cancelled, 0) AS cancelled,
  COALESCE(bk.nights, 0)    AS nights,
  rv.rating,
  COALESCE(rv.reviews, 0)   AS reviews
FROM samples.wanderbricks.destinations AS d
JOIN props ON props.destination_id = d.destination_id
LEFT JOIN bk ON bk.destination_id = d.destination_id
LEFT JOIN rv ON rv.destination_id = d.destination_id
ORDER BY revenue DESC
