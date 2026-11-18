-- The synthetic sample repeats a small set of phrases. Rank phrases, not inferred topics or sentiment.
SELECT p.destination_id, r.comment, COUNT(*) AS reviews, SUM(r.rating) AS rating_sum
FROM samples.wanderbricks.reviews r
JOIN samples.wanderbricks.properties p ON p.property_id = r.property_id
WHERE NOT r.is_deleted AND r.comment IS NOT NULL AND YEAR(r.created_at) = :year
GROUP BY p.destination_id, r.comment
ORDER BY reviews DESC
