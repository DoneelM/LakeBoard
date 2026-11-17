-- Customer reviews for one franchise, newest first. Loaded only when someone picks a franchise.
-- The sample has at most six reviews per franchise; LIMIT keeps it small if the table grows.
SELECT
  TO_DATE(r.review_date) AS review_date,
  r.review
FROM samples.bakehouse.media_customer_reviews AS r
WHERE r.franchiseID = :franchise_id
ORDER BY r.review_date DESC, r.new_id DESC
LIMIT 20
