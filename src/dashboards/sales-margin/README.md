# Sales & Margin (sample)

A finance-style sample dashboard built on the Databricks sample dataset `samples.tpch` (TPC-H), which every
Databricks workspace can read. It replaces nothing; it is here to show how a dashboard folder is put together.

## What it shows

For an order year (1992 to 1998; orders end on 1998-08-02, so 1998 is a part year) and, optionally, a region:

- **Headline tiles**: gross revenue, discount given, net revenue, gross margin, margin % and orders, each against
  the same dates a year earlier.
- **By month**: net revenue or gross margin by month against the prior year.
- **By region → nation → customer**: a drill-down table. Select a region to load its nations, then a nation to load
  its 50 largest customers. Every level downloads as CSV.
- **By market segment**: net revenue with margin %.
- **Late deliveries by ship mode**: the share of order lines received after their commit date.

Definitions (all by order date, `orders.o_orderdate`):

| Measure | SQL |
|---|---|
| Gross revenue | `sum(l_extendedprice)` |
| Net revenue | `sum(l_extendedprice * (1 - l_discount))` |
| Discount given | gross minus net |
| Gross margin | net revenue minus `sum(ps_supplycost * l_quantity)` (supply cost from `partsupp` for the line's part and supplier) |
| Late | `l_receiptdate > l_commitdate` |

Tax (`l_tax`) is left out of every figure.

## Framework features it demonstrates

- **Parameters**: `year` (INT, default 1997), `region` and `nation` (STRING, blank by default) are sent to SQL as
  `:name` markers. Choosing a region filters the tiles, trend, segments and ship modes.
- **Drill-down datasets**: `nations` and `customers` take `:region` / `:nation` and are only requested once the page
  sets that parameter (`dash.setParams` on a row click). Going back up sets them to blank; the query then returns no
  rows in about a second.
- **Shared cache**: every dataset is `cache: shared` with a 24-hour `cache_ttl`, because the sample data has no
  row-level security, everyone may read it, and it never changes. `kpis`, `trend` and `regions` are warmed for 1997.
- **Reconciliation**: the region rows add up to the Net revenue tile, the nation rows add up to their region row,
  and the customer table states what share of its nation's net revenue the top 50 cover. The page shows each check
  under the table and flags a difference.

## Numbers checked

Run on a serverless SQL warehouse, November 2026 (year 1997):

| Check | Value |
|---|---|
| Net revenue tile, all regions | 165,246,449,758.48 |
| Sum of the 5 region rows | 165,246,449,758.48 |
| Europe row | 33,100,640,837.46 |
| Sum of the 5 Europe nation rows | 33,100,640,837.46 |
| Germany row / `nation_net` in customers | 6,644,487,504.84 / 6,644,487,504.84 |

Each query runs in 2 to 9 seconds on a small serverless warehouse and returns at most 50 rows.
