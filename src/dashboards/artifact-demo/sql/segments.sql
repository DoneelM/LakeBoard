-- Order revenue, orders and distinct customers per region and customer market segment, over the same full years.
SELECT
  r.r_name                      AS region,
  c.c_mktsegment                AS segment,
  ROUND(SUM(o.o_totalprice), 2) AS revenue,
  COUNT(*)                      AS orders,
  COUNT(DISTINCT o.o_custkey)   AS customers
FROM samples.tpch.orders o
JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
JOIN samples.tpch.nation n   ON n.n_nationkey = c.c_nationkey
JOIN samples.tpch.region r   ON r.r_regionkey = n.n_regionkey
WHERE o.o_orderdate < DATE '1998-01-01'
GROUP BY r.r_name, c.c_mktsegment
ORDER BY region, segment
