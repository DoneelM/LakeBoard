-- Late deliveries by ship mode for orders placed in the selected year (and region). A line is late when it was
-- received after its commit date.
SELECT
  l.l_shipmode AS ship_mode,
  count(*) AS lines,
  count_if(l.l_receiptdate > l.l_commitdate) AS late_lines,
  round(count_if(l.l_receiptdate > l.l_commitdate) / count(*), 4) AS late_share,
  round(avg(CASE WHEN l.l_receiptdate > l.l_commitdate THEN datediff(l.l_receiptdate, l.l_commitdate) END), 1) AS avg_days_late
FROM samples.tpch.orders o
JOIN samples.tpch.lineitem l ON l.l_orderkey = o.o_orderkey
JOIN samples.tpch.customer c ON c.c_custkey = o.o_custkey
JOIN samples.tpch.nation n ON n.n_nationkey = c.c_nationkey
JOIN samples.tpch.region r ON r.r_regionkey = n.n_regionkey
WHERE o.o_orderdate >= make_date(:year, 1, 1) AND o.o_orderdate < make_date(:year + 1, 1, 1)
  AND (:region IS NULL OR r.r_name = :region)
GROUP BY l.l_shipmode
ORDER BY late_share DESC
