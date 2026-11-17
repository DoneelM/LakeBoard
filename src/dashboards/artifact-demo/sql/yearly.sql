-- Order revenue and order count per region and order year. Full years only (the sample's orders stop in August 1998).
SELECT
  r.r_name                     AS region,
  YEAR(o.o_orderdate)          AS order_year,
  ROUND(SUM(o.o_totalprice), 2) AS revenue,
  COUNT(*)                     AS orders
FROM samples.tpch.orders o
JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
JOIN samples.tpch.nation n   ON n.n_nationkey = c.c_nationkey
JOIN samples.tpch.region r   ON r.r_regionkey = n.n_regionkey
WHERE o.o_orderdate < DATE '1998-01-01'
GROUP BY r.r_name, YEAR(o.o_orderdate)
ORDER BY region, order_year
