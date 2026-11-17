-- Reviews per whole star: a rating of 3.7 counts as 3 stars.
SELECT
  CAST(FLOOR(r.rating) AS INT) AS stars,
  COUNT(*)                     AS reviews
FROM samples.wanderbricks.reviews AS r
JOIN samples.wanderbricks.properties AS p ON p.property_id = r.property_id
WHERE NOT r.is_deleted
  AND (:destination_id IS NULL OR p.destination_id = :destination_id)
GROUP BY CAST(FLOOR(r.rating) AS INT)
ORDER BY stars
