-- One row per franchise: where it is, its size, and its sales over the whole sample period.
-- Franchises with no sales still appear (LEFT JOIN), with zero revenue.
-- Customers are counted only; no customer or card details are read.
WITH sales AS (
  SELECT
    t.franchiseID,
    SUM(t.totalPrice)            AS revenue,
    COUNT(*)                     AS transactions,
    SUM(t.quantity)              AS units,
    COUNT(DISTINCT t.customerID) AS customers
  FROM samples.bakehouse.sales_transactions AS t
  GROUP BY t.franchiseID
)
SELECT
  f.franchiseID          AS franchise_id,
  f.name,
  f.city,
  f.country,
  f.size,
  f.latitude,
  f.longitude,
  COALESCE(s.revenue, 0)      AS revenue,
  COALESCE(s.transactions, 0) AS transactions,
  COALESCE(s.units, 0)        AS units,
  COALESCE(s.customers, 0)    AS customers
FROM samples.bakehouse.sales_franchises AS f
LEFT JOIN sales AS s ON s.franchiseID = f.franchiseID
WHERE :country IS NULL OR f.country = :country
ORDER BY revenue DESC
