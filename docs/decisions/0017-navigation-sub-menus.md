# 0017. Navigation sub-menus (`group:`)

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
A section in the left navigation can collect several closely related dashboards, for example an overview and the
detailed reports behind it. Listed flat, they push the section's other dashboards down and the relation between
them is lost.

## Decision
- A dashboard may set an optional `group:` in `dashboard.yml`: text of 40 characters at most, with no leading or
  trailing spaces. Dashboards in the same section with the same `group` are listed under one collapsible heading,
  indented, with an accent-coloured bar down the left.
- The heading sits where the group's first dashboard (by `order`) would. Ungrouped dashboards are unchanged.
- The group is built with `<details open>`: expanded by default, no script, works from the keyboard.
- The heading text is the `group:` value. Groups only affect the left navigation; home-page cards stay flat. The
  catalogue entry (`catalogue_entry()`) carries `group` so a later home page could use it.

## Why
- Related dashboards stay together without inventing new sections, which are shared across the whole portal.
- `<details>` needs no JavaScript and keeps the navigation accessible.
- Expanded by default, so nobody has to discover that a heading opens.

## Limitations
- One level only. A group cannot contain another group.
- The group name is repeated in each member's `dashboard.yml`; a typo makes a second group. `check.py` does not
  flag near-duplicates.
- `group` (one sub-menu heading) and `groups` (who may open the dashboard) are different keys with similar names.

## Alternatives considered
- More sections: sections are a portal-wide list in `src/environments.yml`, so one team's grouping would show
  for everyone.
- A script-driven tree menu: more code for the same result, and harder to make keyboard-accessible.
- Open only when the current page is inside the group: tried, but hid dashboards that people expected to see.

## Changing it later
`GROUP_MAX_LEN` and the validation are in `src/portal/registry.py`; the rendering is `nav_html` in `src/app.py`;
the styles are the `.pn-group` rules in `src/static/kit.css`.

## Links
- [docs/AUTHORING.md](../AUTHORING.md) (`dashboard.yml`), [docs/DESIGN.md](../DESIGN.md) (Navigation and brand)
