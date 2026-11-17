-- Revenue, units and transactions per product.
SELECT
  t.product,
  SUM(t.totalPrice) AS revenue,
  SUM(t.quantity)   AS units,
  COUNT(*)          AS transactions
FROM samples.bakehouse.sales_transactions AS t
JOIN samples.bakehouse.sales_franchises AS f ON f.franchiseID = t.franchiseID
WHERE :country IS NULL OR f.country = :country
GROUP BY t.product
ORDER BY revenue DESC
