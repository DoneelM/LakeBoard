# Bakery Franchises (sample)

A sample dashboard over the Databricks `samples.bakehouse` data. It shows the whole path a dashboard can take:
a business user builds it as a Claude Dashboard artifact, and the data team moves it into the portal with the page
unchanged.

## What it shows

- **KPI tiles**: revenue, transactions, units sold, average basket (revenue per transaction) and active franchises
  (franchises with at least one sale, out of those listed).
- **Map** of the 48 franchises on OpenStreetMap. Circle area is proportional to revenue. Clicking a circle picks
  that franchise.
- **Customer reviews** of the picked franchise, newest first. The reviews load only when a franchise is picked.
- **Daily revenue** line, **revenue by product** bars and **payment method mix** (share of transactions by card brand).
- **Franchise league table**: name, city, country, size, revenue, transactions, units and customer count. Sortable,
  downloadable as CSV, and clicking a row (or Enter on it) picks the franchise, so the reviews work from the keyboard.
- **Country** filter, sent to SQL. "All countries" sends no value.

## Data

`samples.bakehouse`, the bakery sample that ships with every Databricks workspace. It is a fixed snapshot:
3,333 transactions from 1 to 17 May 2024 across 48 franchises in 9 countries, and 204 reviews from 20 to 31 May 2024.
Money is shown as recorded (whole units, no currency in the data). Days are UTC dates of the transaction time.

| Dataset | SQL | Rows | Parameter |
|---|---|---|---|
| `countries` | `sql/countries.sql` | 9 | none |
| `franchises` | `sql/franchises.sql` | 48 (20 for Japan) | `country` |
| `daily` | `sql/daily.sql` | 17 | `country` |
| `products` | `sql/products.sql` | 6 | `country` |
| `payments` | `sql/payments.sql` | 3 | `country` |
| `reviews` | `sql/reviews.sql` | up to 6 per franchise (20 max) | `franchise_id` |

**Personal data.** The sample has card numbers and customer names, emails, phone numbers and addresses. They are
synthetic, but no query selects them: payments are grouped by card brand only, and customers appear only as a
count per franchise (`COUNT(DISTINCT customerID)`). `sales_customers` and `sales_suppliers` are not read.

**Caching.** Every dataset is `cache: shared`: the sample is readable by every user and has no row-level security,
so one result per filter value serves everyone. The data never changes, so TTLs are long (6 h for sales, 24 h for
the country list and reviews).

Checked: totals across all countries are revenue 66,471, 3,333 transactions; the six products sum to the same
revenue; payment methods split 1,144 Mastercard, 1,106 Amex, 1,083 Visa.

## From Claude artifact to portal

1. **What the business user built.** In claude.ai they made a Claude Dashboard artifact over the bakehouse data and
   wrote `index.html` with the same calls the portal provides: `dash.data('franchises')`, `dash.onData(draw)`,
   `dash.params()` / `dash.setParams({country})`, and the `kit` building blocks and CSS classes (`kit-page`,
   `kit-card`, `kit-grid`, tiles, table, bars, line, map). In the artifact each dataset was a query or an uploaded
   file with the same name and columns.
2. **What the data team added**, without changing the page:
   - one `sql/<dataset>.sql` per `dash.data('<dataset>')` call, aggregated to the grain the page draws, with
     `:country` and `:franchise_id` as parameters instead of filtering in the browser;
   - `dashboard.yml`: title, section and owner, `groups: []`, `libs: [leaflet]` for the map, the two parameters,
     and each dataset's cache, TTL and `source:` note.
3. **Review.** `python scripts/check.py --static` checks the folder (every dataset the page reads is declared, SQL is
   a single read-only statement on allowed catalogs, no scripts from other sites). The data team reviews the SQL for
   cost and grain, confirms no personal columns are selected, and checks the totals above against the source.

If the artifact had filtered in the browser instead of using parameters, that also works unchanged; the parameters
here keep the result sets small and show how `dash.setParams` reloads only the datasets that use a parameter.

## Framework features it shows

- SQL parameters, including an optional one (blank = all) and a parameter that only one dataset uses
  (`franchise_id`), so picking a franchise reloads the reviews and nothing else.
- A dataset loaded on demand: `reviews` is first read with `dash.data('reviews')` only after a franchise is picked.
- `cache: shared` with per-dataset TTLs and `source:` notes in the freshness panel.
- `libs: [leaflet]` and `kit.map`, with circles sized by a measure drawn on the map `kit.map` returns.
- `kit.filters`, `kit.tiles`, `kit.table` (sort, CSV, keyboard row pick), `kit.bars`, `kit.line`, `kit.ready`.
- `data-source` attributes, so each section shows its own loading and refreshing state.
- `dash.genieContext`, ready for when a Genie space is added.

## Adding Ask Genie

There is no `genie:` block because Genie needs a space. To add one, create a Genie space over the four
`samples.bakehouse` sales and review tables (no customer table), then add to `dashboard.yml`:

```yaml
genie:
  space_id: {dev: "<32-character id from the space URL>"}
  sample_questions: ["Which product sells best in Japan?", "Which franchises had no sales on 17 May?"]
  about: Sample bakery franchise sales from 1 to 17 May 2024 and customer reviews from late May 2024.
```

The page already tells Genie the country filter and the picked franchise through `dash.genieContext`.
