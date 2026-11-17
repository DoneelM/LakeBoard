-- Transactions and revenue per payment method (card brand only; card numbers are never read).
SELECT
  t.paymentMethod   AS payment_method,
  COUNT(*)          AS transactions,
  SUM(t.totalPrice) AS revenue
FROM samples.bakehouse.sales_transactions AS t
JOIN samples.bakehouse.sales_franchises AS f ON f.franchiseID = t.franchiseID
WHERE :country IS NULL OR f.country = :country
GROUP BY t.paymentMethod
ORDER BY transactions DESC
