-- A 3.7 rating is in the 3-star bucket. Review-created year is independent of booking check-in year.
SELECT p.destination_id, CAST(FLOOR(r.rating) AS INT) AS stars, COUNT(*) AS reviews
FROM samples.wanderbricks.reviews r
JOIN samples.wanderbricks.properties p ON p.property_id = r.property_id
WHERE NOT r.is_deleted AND YEAR(r.created_at) = :year
GROUP BY p.destination_id, CAST(FLOOR(r.rating) AS INT)
ORDER BY stars DESC
