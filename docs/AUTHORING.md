# Adding a dashboard

This is the contract every dashboard follows, whoever or whatever writes it (a person, Claude Code, Codex,
Cursor or another tool). If the checks in step 5 pass, the portal can host it. The worked example throughout is
[`src/dashboards/city-trips/`](../src/dashboards/city-trips/), which reads the built-in `samples.nyctaxi.trips` table.

For the shared agent workflow, start with [DASHBOARD_WORKFLOW.md](DASHBOARD_WORKFLOW.md). Business authors
using a coding agent and Genie MCP can start with [BUSINESS_AUTHORS.md](BUSINESS_AUTHORS.md). This document
defines the hosting contract; it does not depend on the agent's own preview environment.

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
group: Trip Reports               # optional: dashboards with the same group sit under one collapsible sub-menu
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
    warm_at: startup              # optional with warm:; once per process. Default schedule also runs at warm.times
    data_through: latest_day       # optional DATE result column; latest returned date in the freshness panel
    refresh: always                # optional; rerun on Refresh data if SQL depends on anything beyond table writes
    auth: app                     # optional; needs groups: on the dashboard and on this dataset. Read as the portal's service principal, for people with no access to the data themselves. One shared result, no filters; refreshed in the background every cache_ttl minus 5 minutes
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
| `dash.refreshChanged()` / `dash.refreshAll()` | Refresh loaded datasets selectively, or force every loaded dataset to rerun |
| `dash.genieContext(() => ({ Period: 'Year to date', Region: 'North' }))` | Tells Ask Genie what the page is showing. See "Ask Genie" below |

**`kit`: building blocks**, so dashboards look and behave alike. Use these before writing your own.

| Call | What it does |
|---|---|
| `kit.fmt.num / money / compact / pct / date / month / text` | Formatting in the portal's `locale` (src/environments.yml); blanks show as "–" |
| `kit.num(v)` | Text to number (`null` when blank) |
| `kit.h('div', {class: 'x'}, 'text', child)` | Builds an element. Values are always inserted as text, never as HTML |
| `kit.ready(el, ...datasets)` | Shows "Loading…" or the error in `el` and returns `false` until every dataset is ready |
| `kit.filters(el, specs, onChange)` | Filter bar: `select`, `multi`, `date`, `search`. Returns `{values(), set(id, v), options(id, list)}` |
| `kit.tiles(el, [{label, value, note, tone, spark, delta}])` | KPI tiles. The number in `value` counts up when it changes. `spark: [numbers]` draws a small trend under it; `delta: {value: 0.12, label: 'vs 2001', good: 'up' \| 'down'}` adds a green or red change |
| `kit.insight(el, {eyebrow, title, body, tone, stats: [{value, label}]})` | A headline banner: the one thing the data says. Write the title from the data, so it stays true for any filter |
| `kit.table(el, {columns, rows, csv: 'file-name', onRow})` | Sortable table with a row count and CSV download |
| `kit.bars(el, {rows, label, value, fmt, color(row)})` | Ranked horizontal bars that grow to their new length when the values change |
| `kit.line(el, {rows, x, series: [{key, label, color, dash}], fmt, area, band, marks, spans, tip, xType})` | Lines over time (`x` as `yyyy-MM`, `yyyy-MM-dd` or `yyyy-MM-dd HH:mm`), or over numbers with `xType: 'number'` and `xFmt`. Hover shows every value at that point. `band: {low, high, label}` shades a range (a normal day, a target); `marks: [{x, label, note}]` labels events; `spans: [{from, to, label}]` shades a stretch of time; `tip(row)` adds lines to the tooltip. Lines draw in when the data changes |
| `kit.tip(el)` | A tooltip for your own d3 charts: `.show(x, y, ...elements)` and `.hide()`, in pixels from `el`'s corner |
| `kit.map(el, {tooltip(p), onClick(p), dark})` | Point map on OpenStreetMap (needs `libs: [leaflet]`). `.set(points, {lines})` takes `{lat, lon, color, label, …}`; a `label` draws a numbered pin, and `lines: [{path, color}]` draws routes |
| `kit.colour(i)` | The i-th category colour |
| `kit.csv(name, columns, rows)` | Download rows as CSV |
| `kit.xlsx(name, sheets)` | Download an Excel file for people who edit and print it. `sheets: [{name, columns: [{key, label, width, link}], rows}]`. Returns a promise |

CSS classes: `kit-page` (page padding), `kit-eyebrow` (small label above the title), `kit-card`, `kit-card-sub` (a line under a card's `h2`), `kit-grid`, `kit-btn`, `kit-sub`.
Motion (counting numbers, drawing lines, growing bars, cards rising in) runs only when values change, never on a
resize, and not at all for people whose system asks for reduced motion. Colours come from the theme
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

### Reviews the data team records

Three rules stop a dashboard from loading until a person on the data team has looked at it
([decision 0018](decisions/0018-publishing-guards.md)):

- **The page code is reviewed.** `index.html` (and, for `page: artifact`, every file in `assets/`) must match its
  SHA-256 in `src/reviewed_pages.yml`. The page's JavaScript runs inside the portal, so any edit needs a new review.
- **Shared SQL is reviewed.** Every `cache: shared` dataset (and so every warmed one) must match its SHA-256 in
  `src/shared_cache.yml`. One result is served to every viewer, so the reviewer checks that the SQL and its views
  give the same rows to everyone: no row filters, column masks or `current_user()`.
- **`auth: app` names its audience.** A dataset read as the app needs `groups:` on the dashboard and on the dataset.

After reviewing, the reviewer records the digests in the same pull request:

```bash
python scripts/approve.py <slug>            # prints the entries
python scripts/approve.py <slug> --write    # writes them into src/reviewed_pages.yml and src/shared_cache.yml
```

The digest is of the file's UTF-8 text with LF line endings, so a Windows checkout gives the same value. Authors
don't need to run this; until it is done, `check.py` reports which file has no matching review.

## 6. Record what it replaces

In the dashboard's `README.md`, list the Power BI pages it replaces, any intended differences, and the numbers
you reconciled (period, filters, Power BI value, dashboard value). Reviewers will ask for this. A new dashboard
says what it shows and how its numbers were checked; see `src/dashboards/city-trips/README.md`.

## 7. Open a pull request

Branch from `main`, then follow [PROMOTION.md](PROMOTION.md). Reviewers check the SQL (cost, grain, tables),
the access settings, the page code and the reconciliation, then record the reviews (step 5).

## Importing a Claude dashboard

Business users can build a dashboard as a Claude Dashboard artifact and send the link to the data team. Claude Code
turns it into a draft here with the `import-claude-dashboard` skill
([`.claude/skills/import-claude-dashboard/SKILL.md`](../.claude/skills/import-claude-dashboard/SKILL.md)), which
runs `scripts/import_artifact.py` and `scripts/compare_snapshot.py`.

**What carries over unchanged:** the page (`index.html`, with its extra files in `assets/`, as `page: artifact`),
its parameters (types taken from the defaults and the artifact's rules) and any Databricks SQL query, which becomes
`sql/<id>.sql` with `:name` parameters. The import lands as `status: draft` under Drafts, visible to `drafts_groups`
(`src/environments.yml`) and the dashboard's own `groups`.

**What the data team does:**

- Write the SQL for every dataset marked `todo: true`. Most artifacts show files saved by a scheduled task, so
  there is often no query to copy; the stub SQL lists the tables the artifact named and the columns the page reads.
  When the artifact keeps that task's SQL (a refresh routine in its `dash` store), the import writes it to
  `sql/<id>.sql` but leaves `todo: true` until it is reconciled.
  The file's rows are kept as `snapshots/<id>.json` (gitignored, never committed) to reconcile against with
  `compare_snapshot.py`, and to preview the page locally with `PORTAL_PREVIEW_SNAPSHOTS=1`.
- Find a Unity Catalog source (Lakehouse Federation or ingestion) for anything the artifact read from another
  system.
- Check the page scan in the generated `IMPORT.md`: external URLs, `fetch`, iframes and forms don't work in the
  portal, and theme tokens outside the portal's set may not resolve.
- Set `owner:` and `groups:`, delete the snapshots, and open the pull request. Ask the author before changing what
  the page shows.

Artifact rules LakeBoard doesn't enforce (lists of allowed values, patterns) are noted in the SQL and `IMPORT.md`:
parameters are bound with their type, so a value can't change the query, but any value of that type is accepted.
## Prototyping in another tool

The preferred route is to generate the dashboard directly in the repository against the `dash` and `kit` APIs
above, then preview it in the local portal. Any coding agent with the required file and command tools can follow
the same workflow. An agent-specific artifact or preview is optional.

To adapt an existing prototype:

- Replace uploaded-file or mock-data access with declared datasets in `dashboard.yml`, read-only `sql/*.sql`
  files and `dash.data('<id>')`. Match the returned columns and handle strings and nulls.
- Replace preview-only components and external libraries with `kit` or approved bundled libraries. The hosted
  page is HTML, CSS and JavaScript; it has no React/JSX compilation or agent-provided APIs.
- Use the portal's theme and shell. Remove copies of `dash.js`, `kit.js`, `kit.css`, vendor libraries and shell
  styles that were included just to make an isolated preview work.
- Check every `dash` and `kit` call against this reference, and verify the final page in the portal. A successful
  preview in another product does not prove hosting compatibility.

Claude Dashboard artifacts were the original prototype source and may expose compatible `dash` calls. They
still need the same checks and adaptation; they are not required to create or host a LakeBoard dashboard.


## Shared access and result coverage

Shared user-auth queries are checked as each viewer before a cached result is served. Checks use the full bound
query with `LIMIT 0`; allow decisions last five minutes and deny decisions one minute. Use shared caching only
when rows and masks are identical for every viewer. `auth: app` deliberately requires no source access for viewers.
`data_through: latest_day` names a DATE result column (for example `MAX(event_day) AS latest_day`). The freshness
panel reports the latest returned date separately from the fetch time. Empty/missing dates remain unknown.
