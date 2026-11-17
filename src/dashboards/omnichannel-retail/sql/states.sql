-- Sales per channel and the customer's billing state, for the chosen year. Sales with no address are left out.
WITH lines AS (
  SELECT 'Store' AS channel, s.ss_addr_sk AS addr_sk, s.ss_ext_sales_price AS sales
  FROM samples.tpcds_sf1.store_sales AS s JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = s.ss_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Catalog', c.cs_bill_addr_sk, c.cs_ext_sales_price
  FROM samples.tpcds_sf1.catalog_sales AS c JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = c.cs_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Web', w.ws_bill_addr_sk, w.ws_ext_sales_price
  FROM samples.tpcds_sf1.web_sales AS w JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = w.ws_sold_date_sk
  WHERE d.d_year = :year
)
SELECT lines.channel, a.ca_state AS state, SUM(lines.sales) AS sales
FROM lines
JOIN samples.tpcds_sf1.customer_address AS a ON a.ca_address_sk = lines.addr_sk
WHERE a.ca_state IS NOT NULL
GROUP BY lines.channel, a.ca_state
ORDER BY sales DESC
