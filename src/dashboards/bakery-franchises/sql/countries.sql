-- Countries that have at least one franchise, for the Country filter. Not filtered, so the list never shrinks.
SELECT
  f.country,
  COUNT(*) AS franchises
FROM samples.bakehouse.sales_franchises AS f
GROUP BY f.country
ORDER BY f.country
