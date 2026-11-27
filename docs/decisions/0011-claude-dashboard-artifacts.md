# 0011. Claude Dashboard artifacts run as-is

- **Status:** Accepted
- **Date:** 2026-11-18
- **Links:** branch `feature/claude-artifact-import`

## Context
Business users build dashboards in Claude as "Data" artifacts (Claude Dashboard artifacts). The data team wants to
host them in LakeBoard without rewriting them. An artifact page is `index.html` plus a few flat files (`app.js`,
`theme.css`, …) named by bare name. The artifact host mounts it in `<div id="dash-root">`, runs its scripts in
order, each in its own scope, and gives it `d3` and a `dash` runtime. LakeBoard's `dash.js` already had most of the
data side, but not drawings, loaders, the extra files, or the design tokens the page relies on.

## Decision
A dashboard can say `page: artifact` in `dashboard.yml` (default `page: lakeboard`). Then:

- **Inert page.** `app.py` sends `index.html` unchanged inside `<template id="dash-artifact">` in `#dash-root`,
  so nothing in it loads or runs early. It also loads `static/artifact.css` and `static/artifact.js`.
- **Mounting** (`static/artifact.js`). It drops what the artifact host drops: `type="module"` scripts, `on…=`
  attributes, `<iframe>`, `<object>`, `<base>`. A `<form>` is unwrapped (its contents stay). Bare file names in
  `<link href>`, `<img src>`, `<source>`, `<video>`, `<audio>`, SVG `<image>`/`<use>` become
  `/d/<slug>/assets/<name>`. The page goes into `#dash-root`. After its stylesheets load (at most 3 s), each classic
  script runs in page order, wrapped in `(function () { … }).call(window)`. A `src` script is fetched (same origin
  only) and wrapped the same way. Then drawings start.
- **Extra files** live in `src/dashboards/<slug>/assets/`, served at `GET /d/<slug>/assets/<name>` after the usual
  dashboard access check. Only flat, plain files (no folders, no links) with names of letters, digits, `-`, `_`, `.`
  and these types: `.js .css .png .jpg .jpeg .gif .webp .svg .avif .ico .woff .woff2 .ttf .otf`, up to 5 MB each.
  Anything else is a registry error. Only names the registry accepted are served; others are 404. `assets/` on a
  `page: lakeboard` dashboard is an error. A bare `<script src>`/`<link href>` in `index.html` must name a file in
  `assets/`. Asset scripts are checked like the page: datasets they read must be declared, no outside scripts.
- **Runtime** (`static/dash.js`). Added `dash.draw(name, fn)` and `dash.draw(name, {mount, update, unmount})`
  (ResizeObserver per element, a MutationObserver for `hidden` and removed elements, nested drawings skipped),
  `dash.draw(name)` to rerun, real `dash.loader`, a memoised `dash.calc` that reruns when an input changes or, if
  its `fn` called `dash.params()`, when a filter changes. `data-dash-source-state` now also reports `empty` and
  `stale`, and works on calc ids. On artifact pages only: `dash.colors` holds `var(--chart-N)` strings, a dataset the
  person may not read has status `error` (not `forbidden`), a calc has `data: null` until ready, a failed refresh
  keeps the last rows (`stale`), and `meta` is an object. Every page now gets `truncated` as well as `cut`.
- **Tokens** (`static/shell.css` theme block plus `static/artifact.css`). LakeBoard's own values for the tokens an
  artifact may rely on: `--color-*`, `--font-anthropic-*`, `--cds-font-size-*`, `--cds-font-weight-medium`,
  `--cds-gap-*`, `--cds-pad-*`, `--cds-radius`, `--cds-chart-*`, `--cds-surface-popover`, `--cds-border`,
  `--cds-shadow-popover`, `--cds-text-secondary`, `--cds-dur-slow`, `--cds-ease-out`, and `#dash-root
  { --dash-gutter }` (16 px, 12 px on phones; a page may set 0). Colours follow light and dark mode. Plus
  `.dash-skeleton` and `select.dash-select`.
- **Drafts.** `status: draft` (default `live`) adds a "Draft" badge in the navigation and on the home card. Only
  members of `drafts_groups` (`src/environments.yml`, default `[lakeboard-admins]`, a placeholder) and of the
  dashboard's own `groups` may open it. An empty list means nobody, never everyone. A local run shows drafts to the
  person running it. A `Drafts` section was added.
- **Todo datasets.** A dataset can say `todo: true` (not connected yet), with an optional
  `snapshot: snapshots/<name>.json`. Its `sql:` file may hold only comments; written SQL is still checked.
  `check.py --static` prints a `WARN`; the live check fails on it; the app answers 409 and never runs it, warms it
  or looks up its sources. Only a local run (`PORTAL_LOCAL_PROFILE` set, none of `DATABRICKS_APP_NAME`,
  `DATABRICKS_APP_URL`, `DATABRICKS_APP_PORT` set) with `PORTAL_PREVIEW_SNAPSHOTS=1` serves the snapshot rows
  instead, as strings like SQL results, and the freshness label says "snapshot preview". The snapshot is
  `{"columns": [...], "rows": [[...]]}` or a list of row objects. `src/dashboards/*/snapshots/` is gitignored:
  it holds business data.
- **Sample:** none in `src/dashboards/` now. The runtime is covered by `tests/test_artifact_runtime.py`, which builds artifact pages in a temporary folder (see Update below).

## Why
- People keep building in Claude, where they are quick. The data team hosts the result without a rewrite, so
  what the business approved is what runs.
- No iframe: one document keeps the portal's shell, theme, dark mode, freshness label, Refresh and Ask Genie, and
  the same-origin CSP and access checks apply unchanged.
- The `<template>` keeps the page's HTML byte for byte as written; the runtime adapts around it.
- Drafts and todo datasets let an import land in git before its SQL is ready, without real data in git or in a
  deployed app.

## Limitations
- Not supported from the artifact runtime: the Sources panel, connectors and live calls from the page, comments,
  and per-viewer stored state. Sources are SQL files reviewed in git, so the statuses `connect` and `declined`
  never occur.
- `dash.loader` gets rows, not a source's raw answer. A loader that parses text or JSON must be rewritten to work on
  rows. Its return is used only when it is an array.
- `data-field`, `data-where`, `data-row` and `data-row-key` are left in place but do nothing.
- Values arrive as strings (or null), as on every LakeBoard page; pages convert numbers.
- Scripts are wrapped in a function, so a top-level `return` or `"use strict"` behaves as inside a function, and
  `document.currentScript` is not the page's script.
- `url()` in inline styles is not rewritten to `assets/` (in `.css` files it works, since they load from there).
- `kit.js` and `kit.css` still load; artifact pages just don't use them.
- Drafts are hidden, not secret: anyone with repository access can read them.

## Alternatives considered
- **A sandboxed iframe per page.** Isolates the page, but loses the shell's theme, dark mode and freshness label,
  needs a message bridge for `dash`, and makes height, printing and focus awkward. The page is already reviewed
  code under the portal's CSP, so isolation buys little.
- **Rewriting pages on import** into LakeBoard style (`kit`, one `index.html`). Every import becomes a hand
  rewrite that drifts from what the business approved, and re-importing a changed artifact means doing it again.
- **Serving the page at `/d/<slug>/`** so bare names resolve by URL. It breaks existing links and still runs
  scripts in the global scope.

## Changing it later
`page:`, `status:`, `todo:` and `snapshot:` are read in `src/portal/registry.py`; `drafts_groups` in
`src/environments.yml`; the page wrapper and asset route in `src/app.py`; mounting in `src/static/artifact.js`;
the runtime in `src/static/dash.js`; tokens in `src/static/shell.css` and `src/static/artifact.css`; the snapshot
preview in `src/portal/snapshots.py`.

## Update 2026-11-26: the sample page was removed
`src/dashboards/artifact-demo/` read `samples.tpch`, whose values are spread evenly, so every chart on it was flat. It
was removed with the other TPC-H sample (decision 0021). The runtime is unchanged and still covered by
`tests/test_artifact_runtime.py`, which builds artifact pages in a temporary folder. The next imported Claude
artifact (skill `import-claude-dashboard`) becomes the working example.

## Links
`tests/test_artifact_runtime.py`; `docs/DESIGN.md` (Page runtime).
