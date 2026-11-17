-- Revenue, transactions and units per day (UTC date of the transaction).
SELECT
  TO_DATE(t.dateTime) AS day,
  SUM(t.totalPrice)   AS revenue,
  COUNT(*)            AS transactions,
  SUM(t.quantity)     AS units
FROM samples.bakehouse.sales_transactions AS t
JOIN samples.bakehouse.sales_franchises AS f ON f.franchiseID = t.franchiseID
WHERE :country IS NULL OR f.country = :country
GROUP BY TO_DATE(t.dateTime)
ORDER BY day
