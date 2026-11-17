# Adding a dashboard

This is the contract every dashboard follows, whoever or whatever writes it (a person, Claude Code, Codex,
Cursor or another tool). If the checks in step 5 pass, the portal can host it. The worked example throughout is
[`src/dashboards/city-trips/`](../src/dashboards/city-trips/), which reads the built-in `samples.nyctaxi.trips` table.

A dashboard is one folder. Nothing outside the folder changes.

```
src/dashboards/<slug>/          slug: lowercase letters, digits and hyphens. It becomes the URL /d/<slug>
  dashboard.yml                 what it is, where it sits in the left navigation, its datasets and filters
  index.html                    the page (HTML + CSS + JavaScript in one file)
  sql/<name>.sql                one query per dataset
  README.md                     what it replaces, and how its numbers were checked
```

## 1. Start from the template

```bash
python scripts/new_dashboard.py my-dashboard "My dashboard" --owner Operations --section Operations
./scripts/run_local.sh <cli-profile> <warehouse-id>     # or: ./scripts/run_local.ps1 -Profile <p> -Warehouse <id>
```

The local portal runs on http://localhost:8000, signed in as you through your Databricks CLI profile.

## 2. `dashboard.yml`

```yaml
title: City Trips
description: One sentence on the question this dashboard answers.   # shown on the home page and as a tooltip
owner: Samples                    # the team that owns the content
section: Samples                  # heading in the left navigation; the list is in src/environments.yml
order: 10                         # position within the section
replaces: "Power BI: Taxi Trips (Operations workspace)"   # optional
groups: []                        # workspace groups that may open it; [] = everyone who can use the portal
environments: [dev, test]         # optional; leave out to show it everywhere. Use it to keep unfinished work out of prod
libs: [leaflet]                   # optional extra libraries; the list is in src/environments.yml
params:                           # filters that are sent to SQL (everything else filters in the browser)
  date_from: {type: DATE, default: "2016-01-01"}   # or @week_start (Monday), @week_end (Friday), @today
  date_to:   {type: DATE, default: "2016-02-29"}
datasets:
  daily:                          # the page reads this with dash.data('daily')
    title: Trips by day
    description: What it holds, in a sentence.
    sql: sql/daily.sql
    cache_ttl: 24h                # how long a result is reused: 15m, 1h, 6h, 24h. Default 1h. See "How data refreshes" in OPERATIONS.md
    cache: shared                 # optional; one result for all viewers. Only for data with no row-level security
    warm:                         # optional, needs cache: shared; pre-loaded at the warm times (src/environments.yml) and once at app start
      - {date_from: "2016-01-01", date_to: "2016-02-29"}
    auth: app                     # optional; read as the portal's service principal, for people with no access to the data themselves. One shared result, no filters; refreshed in the background every cache_ttl minus 5 minutes
    background: false             # optional, with auth: app; load on demand once the result has expired, not kept refreshed
    groups: []                    # optional; restrict just this dataset to some workspace groups
    source: "Rebuilt by the nightly trips job at 02:00 UTC"   # optional; see below
genie:                            # optional; adds the "Ask Genie" bar. See "Ask Genie" below
  space_id: {prod: "0123456789abcdef0123456789abcdef"}   # per environment; no id there = no bar there
  sample_questions: ["Which pickup ZIP codes had the highest average fare?"]   # up to 5
  about: One or two sentences telling Genie what this dashboard shows.
```

Parameter types: `STRING`, `INT`, `BIGINT`, `DOUBLE`, `DECIMAL`, `DATE`, `TIMESTAMP`, `BOOLEAN`.

**`source:`** (optional, per dataset) is one plain sentence, at most 200 characters, saying how and when the data
behind the dataset is built, for example which job rebuilds it and at what times. It appears in the freshness panel
that opens from "Data as of …" in the title bar, so people can tell whether pressing Refresh is worth it. Write
only what you have checked (the job's schedule, or the table history), and leave it out if you don't know. When the
source tables last changed is found automatically; don't put times that change into this note.

## 3. SQL rules

- One `SELECT` or `WITH` statement per file. No DDL or DML.
- Write every table as `catalog.schema.table`, using the **prod** catalog name. When `src/environments.yml` maps
  that catalog to another name in dev or test (for example `main_prod` to `main_dev`), the portal swaps it there,
  so the same file runs everywhere and can be pasted into the SQL editor unchanged. `samples` is the same
  everywhere, so City Trips just writes `samples.nyctaxi.trips`.
- Only catalogs listed under `catalogs:` in `src/environments.yml` are allowed. Add yours there.
- Use `:name` for filter values and declare each one under `params`. Never build SQL from text in the page.
- Aggregate in SQL to the grain the page needs. Aim for under 100,000 rows; the hard limit is 500,000.
- Queries run as the person viewing the page, so they only return what that person may see in Unity Catalog.

## 4. The page (`index.html`)

The portal wraps the page in the shell (left navigation, title bar, Refresh button), so the file holds only the
dashboard's own content. Two libraries are always available:

**`dash`: data and filters**

| Call | What it does |
|---|---|
| `dash.data('id')` | `{status, data, message, refreshing, cut, fetchedAt}`. `status` is `loading`, `ok`, `error` or `forbidden`. `data` is an array of rows; every value is a string or `null` |
| `dash.onData(fn)` | Runs `fn` now and whenever any dataset changes. Draw the whole page from here |
| `dash.params()` / `dash.setParams({...})` / `dash.resetParams()` | Read or change SQL parameters. Datasets that use a changed parameter reload |
| `dash.allowed('id')` | Whether this person may read a group-restricted dataset |
| `dash.refresh('id')` | Re-run one dataset, ignoring the cache. For a shared dataset the new result is what everyone sees |
| `dash.genieContext(() => ({ Period: 'Year to date', Region: 'North' }))` | Tells Ask Genie what the page is showing. See "Ask Genie" below |

**`kit`: building blocks**, so dashboards look and behave alike. Use these before writing your own.

| Call | What it does |
|---|---|
| `kit.fmt.num / money / compact / pct / date / month / text` | Formatting in the portal's `locale` (src/environments.yml); blanks show as "–" |
| `kit.num(v)` | Text to number (`null` when blank) |
| `kit.h('div', {class: 'x'}, 'text', child)` | Builds an element. Values are always inserted as text, never as HTML |
| `kit.ready(el, ...datasets)` | Shows "Loading…" or the error in `el` and returns `false` until every dataset is ready |
| `kit.filters(el, specs, onChange)` | Filter bar: `select`, `multi`, `date`, `search`. Returns `{values(), set(id, v), options(id, list)}` |
| `kit.tiles(el, [{label, value, note, tone}])` | KPI tiles |
| `kit.table(el, {columns, rows, csv: 'file-name', onRow})` | Sortable table with a row count and CSV download |
| `kit.bars(el, {rows, label, value, fmt})` | Ranked horizontal bars |
| `kit.line(el, {rows, x, series: [{key, label}], fmt})` | Lines over time |
| `kit.map(el, {tooltip(p), onClick(p), dark})` | Point map on OpenStreetMap (needs `libs: [leaflet]`). `.set(points, {lines})` takes `{lat, lon, color, label, …}`; a `label` draws a numbered pin, and `lines: [{path, color}]` draws routes |
| `kit.colour(i)` | The i-th category colour |
| `kit.csv(name, columns, rows)` | Download rows as CSV |
| `kit.xlsx(name, sheets)` | Download an Excel file for people who edit and print it. `sheets: [{name, columns: [{key, label, width, link}], rows}]`. Returns a promise |

CSS classes: `kit-page` (page padding), `kit-card`, `kit-grid`, `kit-btn`, `kit-sub`. Colours come from the theme
variables at the top of `src/static/shell.css` (`--color-fg`, `--color-fg-muted`, `--color-bg`, `--color-panel`,
`--color-border-line`, `--brand`, `--accent`, `--chart-1` to `--chart-8`), which switch between light and dark
automatically. `dash.colors` holds the chart colours. `d3` (version 7) is available for custom charts.
`{{LOGO}}` in the page is replaced with the portal's logo (`brand.logo`).

Minimal page:

```html
<div class="kit-page">
  <h1>Revenue by month</h1>
  <div class="kit-card" id="chart"></div>
</div>
<script>
dash.onData(() => {
  const d = dash.data('revenue');
  if (!kit.ready('#chart', d)) return;
  kit.line('#chart', { rows: d.data, x: 'month', series: [{ key: 'revenue', label: 'Revenue' }], fmt: kit.fmt.compact });
});
</script>
```

**Page rules**

- No scripts, styles, fonts or data from other websites. The browser blocks them (the portal sends a
  Content-Security-Policy), and the checks reject `<script src="https://…">`. Ask whoever runs the portal to add a library under `libs:`.
- Don't send data anywhere. A page can only call the portal itself.
- Prefix your own CSS classes and element ids (City Trips uses `ct-`), so they can't clash with the shell.
- Handle `loading`, `error` and empty results on every chart and table (`kit.ready` does the first two).
- Use the theme variables, not fixed colours, so the page follows the portal's brand and dark mode.
- It must work at phone width and with the keyboard.

### Ask Genie (optional)

A dashboard can have an "Ask Genie about this dashboard…" bar at the bottom of the page. People type a question;
a Genie space answers it with their own data access, and the panel shows the answer, a small table and the SQL.

1. **Find or build a Genie space** over the same views the dashboard reads. Whoever runs the portal usually owns them.
   The space id is the 32-character code in the space's URL.
2. **Add the `genie:` block** to `dashboard.yml`. Put the id under each environment that has a space, in quotes.
   An environment without an id shows no bar.
3. **Write `about`** in one or two sentences: what the dashboard covers, and anything Genie would otherwise get
   wrong (which currency, which definition of a trip). It is sent to Genie with the first question.
4. **Add 3 to 5 `sample_questions`** that the space can answer. They appear as buttons when the panel is empty.
5. **Describe the current view** if the page filters in the browser. Genie can't see those filters, so tell it:
   ```js
   dash.genieContext(() => ({ Period: 'January 2016', Borough: state.borough || 'All' }));
   ```
   The function runs each time someone opens the panel or sends a question. Return a flat object of short
   label → text pairs (at most 20; labels under 40 characters, values under 200). Leave out empty filters.
   Declared SQL `params` are added for you.

Rules: `genie:` is refused on a dashboard with an `auth: app` dataset, because Genie answers as the viewer, who
may not be able to read that data. The space must cover the dashboard's own views, or its numbers won't match.

## 5. Check it

```powershell
python scripts/check.py --static; pytest -q                       # rules above; no Databricks needed
python scripts/check.py --env dev --profile <profile> --warehouse <id>   # runs every query (LIMIT 0) with dev catalog names
```

The pull request pipeline runs the first line. Each deployment runs the second against its own environment.

## 6. Record what it replaces

In the dashboard's `README.md`, list the Power BI pages it replaces, any intended differences, and the numbers
you reconciled (period, filters, Power BI value, dashboard value). Reviewers will ask for this. A new dashboard
says what it shows and how its numbers were checked; see `src/dashboards/city-trips/README.md`.

## 7. Open a pull request

Branch from `main`, then follow [PROMOTION.md](PROMOTION.md). Reviewers check the SQL (cost, grain, tables),
the access settings, and the reconciliation.

## Prototyping as a Claude artifact

A Claude Dashboard artifact provides `dash.data` / `dash.onData`, so the data side of a prototype carries over:
the uploaded files become `sql/*.sql` datasets with the same ids. The artifact does not provide `kit`, the portal's
theme variables or the shell. So:

- A prototype that uses only `dash`, its own HTML and CSS, and `d3` moves into `index.html` unchanged.
- A prototype that uses `kit` only works in the artifact if the contents of `src/static/kit.js`, `src/static/kit.css`
  and the theme block at the top of `src/static/shell.css` are pasted into it. Delete those copies when you move
  it into the folder: the portal loads its own. Nothing does this step for you.
- Check every `dash` call against the table above. The portal implements only those.
