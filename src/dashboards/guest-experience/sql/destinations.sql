-- Reviews, average rating and the share of low (under 2.5) and high (4 or more) ratings per destination.
-- Deleted reviews are left out.
SELECT
  d.destination_id,
  d.destination,
  d.country,
  COUNT(*)                                  AS reviews,
  AVG(r.rating)                             AS rating,
  AVG(CASE WHEN r.rating < 2.5 THEN 1 ELSE 0 END)  AS low_share,
  AVG(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END)   AS high_share
FROM samples.wanderbricks.reviews AS r
JOIN samples.wanderbricks.properties AS p ON p.property_id = r.property_id
JOIN samples.wanderbricks.destinations AS d ON d.destination_id = p.destination_id
WHERE NOT r.is_deleted
GROUP BY d.destination_id, d.destination, d.country
ORDER BY rating DESC
