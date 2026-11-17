-- Line items sold per channel and hour of the day (store till time, or catalog and web order time), for the chosen year.
WITH lines AS (
  SELECT 'Store' AS channel, s.ss_sold_time_sk AS time_sk
  FROM samples.tpcds_sf1.store_sales AS s JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = s.ss_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Catalog', c.cs_sold_time_sk
  FROM samples.tpcds_sf1.catalog_sales AS c JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = c.cs_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Web', w.ws_sold_time_sk
  FROM samples.tpcds_sf1.web_sales AS w JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = w.ws_sold_date_sk
  WHERE d.d_year = :year
)
SELECT lines.channel, t.t_hour AS hour, COUNT(*) AS items
FROM lines
JOIN samples.tpcds_sf1.time_dim AS t ON t.t_time_sk = lines.time_sk
GROUP BY lines.channel, t.t_hour
ORDER BY lines.channel, hour
