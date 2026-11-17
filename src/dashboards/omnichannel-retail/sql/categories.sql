-- Sales and returns per channel and item category, for the chosen year. Returns are counted in the year they were
-- returned, so a return can belong to a sale from the year before.
WITH sold AS (
  SELECT 'Store' AS channel, s.ss_item_sk AS item_sk, s.ss_ext_sales_price AS sales
  FROM samples.tpcds_sf1.store_sales AS s JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = s.ss_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Catalog', c.cs_item_sk, c.cs_ext_sales_price
  FROM samples.tpcds_sf1.catalog_sales AS c JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = c.cs_sold_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Web', w.ws_item_sk, w.ws_ext_sales_price
  FROM samples.tpcds_sf1.web_sales AS w JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = w.ws_sold_date_sk
  WHERE d.d_year = :year
),
returned AS (
  SELECT 'Store' AS channel, r.sr_item_sk AS item_sk, r.sr_return_amt AS amount
  FROM samples.tpcds_sf1.store_returns AS r JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = r.sr_returned_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Catalog', r.cr_item_sk, r.cr_return_amount
  FROM samples.tpcds_sf1.catalog_returns AS r JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = r.cr_returned_date_sk
  WHERE d.d_year = :year
  UNION ALL
  SELECT 'Web', r.wr_item_sk, r.wr_return_amt
  FROM samples.tpcds_sf1.web_returns AS r JOIN samples.tpcds_sf1.date_dim AS d ON d.d_date_sk = r.wr_returned_date_sk
  WHERE d.d_year = :year
),
s AS (
  SELECT sold.channel, COALESCE(i.i_category, 'Uncategorised') AS category, SUM(sold.sales) AS sales
  FROM sold JOIN samples.tpcds_sf1.item AS i ON i.i_item_sk = sold.item_sk
  GROUP BY sold.channel, COALESCE(i.i_category, 'Uncategorised')
),
r AS (
  SELECT returned.channel, COALESCE(i.i_category, 'Uncategorised') AS category, SUM(returned.amount) AS returns
  FROM returned JOIN samples.tpcds_sf1.item AS i ON i.i_item_sk = returned.item_sk
  GROUP BY returned.channel, COALESCE(i.i_category, 'Uncategorised')
)
SELECT s.channel, s.category, s.sales, COALESCE(r.returns, 0) AS returns
FROM s LEFT JOIN r ON r.channel = s.channel AND r.category = s.category
ORDER BY s.sales DESC
