-- Drill-down level 2: the nations in one region. The page asks for it only once a region is picked.
-- Its rows add up to that region's row in regions.sql.
SELECT
  n.n_name AS nation,
  round(sum(l.l_extendedprice), 2) AS gross,
  round(sum(l.l_extendedprice * (1 - l.l_discount)), 2) AS net,
  round(sum(l.l_extendedprice * l.l_discount), 2) AS discount,
  round(sum(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity), 2) AS margin,
  count(DISTINCT o.o_orderkey) AS orders,
  count(DISTINCT o.o_custkey) AS customers
FROM samples.tpch.orders o
JOIN samples.tpch.lineitem l ON l.l_orderkey = o.o_orderkey
JOIN samples.tpch.partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey
JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
JOIN samples.tpch.nation n ON n.n_nationkey = c.c_nationkey
JOIN samples.tpch.region r ON r.r_regionkey = n.n_regionkey
WHERE o.o_orderdate >= make_date(:year, 1, 1) AND o.o_orderdate < make_date(:year + 1, 1, 1)
  AND r.r_name = :region
GROUP BY n.n_name
ORDER BY net DESC
