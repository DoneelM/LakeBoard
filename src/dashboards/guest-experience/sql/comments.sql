-- Each review comment with how often it was left and its average rating. The sample's comments come from a small
-- set of phrases, so this ranks what guests say most.
SELECT
  r.comment,
  COUNT(*)      AS reviews,
  AVG(r.rating) AS rating
FROM samples.wanderbricks.reviews AS r
JOIN samples.wanderbricks.properties AS p ON p.property_id = r.property_id
WHERE NOT r.is_deleted
  AND r.comment IS NOT NULL
  AND (:destination_id IS NULL OR p.destination_id = :destination_id)
GROUP BY r.comment
ORDER BY reviews DESC
