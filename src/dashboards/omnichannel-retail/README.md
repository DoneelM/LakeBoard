# Omnichannel Retail (sample)

A sample dashboard over `samples.tpcds_sf1`, the TPC-DS benchmark data (scale factor 1) that ships with Databricks.
It unions three sales channels and their returns over a star schema, with a year-on-year comparison.

## What it shows

- **KPI tiles** for the chosen year against the year before: sales, orders, average order, the August to December
  share of the year's sales, and the web share.
- **Sales by month** per channel (the holiday peak), the **channel mix** and the **average order by channel**.
- **When each channel sells**: share of each channel's line items by hour of the day.
- **Return rate by category**, **top customer states** and a **category by channel** table (sortable, CSV).
- **Filter**: year (1998 to 2002), sent to SQL.

## Data

`samples.tpcds_sf1`: store, catalog and web sales and returns from January 1998 to early January 2003 (generated data).
Sales are `ext_sales_price`; an order is a store ticket or a catalog or web order number. Returns are counted in the
year they were returned. TPC-DS profit columns are negative overall by design of the generator, so profit isn't shown.

| Dataset | SQL | Rows | Parameters |
|---|---|---|---|
| `monthly` | `sql/monthly.sql` | 72 | `year` |
| `hours` | `sql/hours.sql` | about 60 | `year` |
| `categories` | `sql/categories.sql` | 33 | `year` |
| `states` | `sql/states.sql` | about 150 | `year` |

## How the numbers were checked

Against direct queries for 2002: store sales $1.025 billion, catalog $729 million, web $366 million; store sales in
December 2002 $170.2 million and February 2002 $44.7 million; Texas is the top customer state.
