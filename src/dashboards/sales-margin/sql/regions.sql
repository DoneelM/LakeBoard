-- Drill-down level 1: revenue and margin by region for the selected year. Not filtered by region, so its rows
-- add up to the KPI tiles when no region is picked (the page shows that check).
SELECT
  r.r_name AS region,
  round(sum(l.l_extendedprice), 2) AS gross,
  round(sum(l.l_extendedprice * (1 - l.l_discount)), 2) AS net,
  round(sum(l.l_extendedprice * l.l_discount), 2) AS discount,
  round(sum(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity), 2) AS margin,
  count(DISTINCT o.o_orderkey) AS orders
FROM samples.tpch.orders o
JOIN samples.tpch.lineitem l ON l.l_orderkey = o.o_orderkey
JOIN samples.tpch.partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey
JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
JOIN samples.tpch.nation n ON n.n_nationkey = c.c_nationkey
JOIN samples.tpch.region r ON r.r_regionkey = n.n_regionkey
WHERE o.o_orderdate >= make_date(:year, 1, 1) AND o.o_orderdate < make_date(:year + 1, 1, 1)
GROUP BY r.r_name
ORDER BY net DESC
