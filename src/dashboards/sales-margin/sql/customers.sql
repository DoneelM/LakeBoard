-- Drill-down level 3: the 50 largest customers in one nation by net revenue. The page asks for it only once a
-- nation is picked. nation_net and nation_customers cover every customer in the nation, so the page can say how
-- much of the nation the top 50 cover (nation_net equals the nation's row in nations.sql).
WITH by_customer AS (
  SELECT
    c.c_custkey AS custkey, c.c_name AS customer, c.c_mktsegment AS segment,
    sum(l.l_extendedprice * (1 - l.l_discount)) AS net,
    sum(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity) AS margin,
    sum(l.l_extendedprice * l.l_discount) AS discount,
    count(DISTINCT o.o_orderkey) AS orders
  FROM samples.tpch.orders o
  JOIN samples.tpch.lineitem l ON l.l_orderkey = o.o_orderkey
  JOIN samples.tpch.partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey
  JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
  JOIN samples.tpch.nation n ON n.n_nationkey = c.c_nationkey
  WHERE o.o_orderdate >= make_date(:year, 1, 1) AND o.o_orderdate < make_date(:year + 1, 1, 1)
    AND n.n_name = :nation
  GROUP BY c.c_custkey, c.c_name, c.c_mktsegment
)
SELECT custkey, customer, segment,
  round(net, 2) AS net, round(margin, 2) AS margin, round(discount, 2) AS discount, orders,
  round(sum(net) OVER (), 2) AS nation_net,
  count(*) OVER () AS nation_customers
FROM by_customer
ORDER BY net DESC
LIMIT 50
