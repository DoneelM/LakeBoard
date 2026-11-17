-- Sales (extended sales price) and orders per channel and month, for the chosen year and the year before.
-- An order is a store ticket, or a catalog or web order number.
WITH lines AS (
  SELECT 'Store' AS channel, d.d_date AS day, s.ss_ext_sales_price AS sales, s.ss_ticket_number AS order_no
  FROM samples.tpcds_sf1.store_sales AS s JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = s.ss_sold_date_sk
  WHERE d.d_year IN (:year, :year - 1)
  UNION ALL
  SELECT 'Catalog', d.d_date, c.cs_ext_sales_price, c.cs_order_number
  FROM samples.tpcds_sf1.catalog_sales AS c JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = c.cs_sold_date_sk
  WHERE d.d_year IN (:year, :year - 1)
  UNION ALL
  SELECT 'Web', d.d_date, w.ws_ext_sales_price, w.ws_order_number
  FROM samples.tpcds_sf1.web_sales AS w JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = w.ws_sold_date_sk
  WHERE d.d_year IN (:year, :year - 1)
)
SELECT
  channel,
  DATE_FORMAT(day, 'yyyy-MM')  AS month,
  SUM(sales)                   AS sales,
  COUNT(DISTINCT order_no)     AS orders
FROM lines
GROUP BY channel, DATE_FORMAT(day, 'yyyy-MM')
ORDER BY month, channel
