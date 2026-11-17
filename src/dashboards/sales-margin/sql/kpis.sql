-- KPI tiles: one row for the selected year (and region, when one is picked) beside the same dates a year earlier.
-- Revenue is booked by order date. Margin = net revenue - supply cost (partsupp.ps_supplycost x quantity).
-- 1998 is a part year (orders end 1998-08-02), so the prior year is cut to the same day of the year.
WITH span AS (
  SELECT make_date(:year, 1, 1) AS cy_start,
         least(make_date(:year, 12, 31), max(o_orderdate)) AS cy_end
  FROM samples.tpch.orders
),
lines AS (
  SELECT
    CASE WHEN o.o_orderdate >= s.cy_start THEN 'cy' ELSE 'py' END AS period,
    o.o_orderkey, o.o_custkey,
    l.l_extendedprice AS gross,
    l.l_extendedprice * (1 - l.l_discount) AS net,
    ps.ps_supplycost * l.l_quantity AS cost
  FROM samples.tpch.orders o
  CROSS JOIN span s
  JOIN samples.tpch.lineitem l ON l.l_orderkey = o.o_orderkey
  JOIN samples.tpch.partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey
  JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
  JOIN samples.tpch.nation n ON n.n_nationkey = c.c_nationkey
  JOIN samples.tpch.region r ON r.r_regionkey = n.n_regionkey
  WHERE o.o_orderdate >= make_date(:year - 1, 1, 1) AND o.o_orderdate <= make_date(:year, 12, 31)
    AND (o.o_orderdate BETWEEN s.cy_start AND s.cy_end
         OR o.o_orderdate BETWEEN add_months(s.cy_start, -12) AND add_months(s.cy_end, -12))
    AND (:region IS NULL OR r.r_name = :region)
)
SELECT
  (SELECT cy_start FROM span) AS period_start,
  (SELECT cy_end FROM span) AS period_end,
  round(sum(CASE WHEN period = 'cy' THEN gross END), 2) AS gross,
  round(sum(CASE WHEN period = 'cy' THEN net END), 2) AS net,
  round(sum(CASE WHEN period = 'cy' THEN gross - net END), 2) AS discount,
  round(sum(CASE WHEN period = 'cy' THEN net - cost END), 2) AS margin,
  count(DISTINCT CASE WHEN period = 'cy' THEN o_orderkey END) AS orders,
  count(DISTINCT CASE WHEN period = 'cy' THEN o_custkey END) AS customers,
  round(sum(CASE WHEN period = 'py' THEN gross END), 2) AS py_gross,
  round(sum(CASE WHEN period = 'py' THEN net END), 2) AS py_net,
  round(sum(CASE WHEN period = 'py' THEN gross - net END), 2) AS py_discount,
  round(sum(CASE WHEN period = 'py' THEN net - cost END), 2) AS py_margin
FROM lines
