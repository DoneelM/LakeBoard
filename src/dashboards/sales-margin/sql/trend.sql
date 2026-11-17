-- Net revenue and margin by month for the selected year (and region) beside the same months a year earlier.
-- The prior year is cut to the same day of the year, so a part year (1998) compares like with like.
WITH span AS (
  SELECT make_date(:year, 1, 1) AS cy_start,
         least(make_date(:year, 12, 31), max(o_orderdate)) AS cy_end
  FROM samples.tpch.orders
),
lines AS (
  SELECT
    month(o.o_orderdate) AS m,
    CASE WHEN o.o_orderdate >= s.cy_start THEN 'cy' ELSE 'py' END AS period,
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
  date_format(make_date(:year, m, 1), 'yyyy-MM') AS month,
  round(sum(CASE WHEN period = 'cy' THEN net END), 2) AS net,
  round(sum(CASE WHEN period = 'py' THEN net END), 2) AS py_net,
  round(sum(CASE WHEN period = 'cy' THEN net - cost END), 2) AS margin,
  round(sum(CASE WHEN period = 'py' THEN net - cost END), 2) AS py_margin
FROM lines
GROUP BY m
ORDER BY m
