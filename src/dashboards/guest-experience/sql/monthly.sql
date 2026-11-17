-- Reviews per month with the average rating and the share of low (under 2.5) and high (4 or more) ratings.
-- Only a handful of reviews come before June 2023, so the trend starts there.
SELECT
  DATE_FORMAT(r.created_at, 'yyyy-MM')             AS month,
  COUNT(*)                                         AS reviews,
  AVG(r.rating)                                    AS rating,
  AVG(CASE WHEN r.rating < 2.5 THEN 1 ELSE 0 END)  AS low_share,
  AVG(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END)   AS high_share
FROM samples.wanderbricks.reviews AS r
JOIN samples.wanderbricks.properties AS p ON p.property_id = r.property_id
WHERE NOT r.is_deleted
  AND r.created_at >= TIMESTAMP'2023-06-01 00:00:00'
  AND (:destination_id IS NULL OR p.destination_id = :destination_id)
GROUP BY DATE_FORMAT(r.created_at, 'yyyy-MM')
ORDER BY month
