# Moving a report from Power BI

The aim is that people open the portal and find the same reports, in the same order, working faster. Each
report goes through the same six steps.

## 1. Find out who uses it

```bash
az login
python scripts/powerbi_usage.py --days 28
```

This reads report views from the Power BI admin activity log and writes three files to `usage/` (not committed,
because they hold email addresses):

| File | Use |
|---|---|
| `reports.csv` | Views and distinct users per report. Decides what to migrate first and what to retire instead |
| `report_users.csv` | Views, days used and last viewed per report and person. This is the comms list |
| `views.csv` | Every view, including whether it came through the Power BI app, a workspace or Teams |

Power BI keeps this log for about 28 days. Run the script every few weeks during the migration and keep the
files if you need a longer history. It works for a Fabric administrator's own login, or with `--sp` for a
service principal once a Fabric admin has allowed service principals to read the admin APIs.

## 2. Decide: migrate, merge or retire

- Nobody opened it in 28 days: ask the owner, then retire it.
- A handful of users and it overlaps another report: fold it into that dashboard.
- Paginated reports, emailed subscriptions and data alerts have no equivalent in the portal yet. Check
  `views.csv` and the report's subscriptions before promising a date.

## 3. Map the report

From the report's `.Report` and `.SemanticModel` folders (Power BI Project format), list:

- the visible pages, visuals, slicers and their defaults;
- each measure, and the tables and filters behind it;
- the source views in Unity Catalog (the semantic model's M queries name them);
- row-level security roles. These become Unity Catalog row filters or group settings, not page logic.

## 4. Build it

With Claude Code, open the repository and ask it to migrate the report, giving the path to the `.pbip` file or
the report's folder. It follows the `migrate-power-bi` skill (`.claude/skills/migrate-power-bi/SKILL.md`), which
covers steps 3 to 5. Other tools can follow the same file.

To see the whole report at once, run `python scripts/pbip_summary.py <path to .pbip or folder>` (`--json` for
JSON). It only reads the files. It lists sources, measures, relationships, security roles, pages, visuals and
slicers, and marks DAX that needs care: time intelligence, filter context and measures that don't add up.

Follow [AUTHORING.md](AUTHORING.md). Scaffold with `scripts/new_dashboard.py`, which also writes a `README.md`
with a table for mapping Power BI pages to the new page. Rewrite each measure as SQL at the grain the page needs.
Keep the page names and filter order people know, and fix what is broken rather than copying it. Set `replaces:`
in `dashboard.yml` to the report's name.

## 5. Prove the numbers

Pick two or three periods and filter combinations. Record the Power BI value and the dashboard value for each
measure in the dashboard's `README.md`, with an explanation for any difference. The business owner signs off in
test.

## 6. Cut over

1. Release to prod with the dashboard visible to its groups.
2. Email the people in `report_users.csv`: what moved, the new link, what changed, who to ask.
3. Add a text box to the top of the Power BI report: "This report has moved" with the link.
4. Run both for one reporting cycle (a month-end for finance, a fortnight for operations).
5. Check the portal's usage log ([OPERATIONS.md](OPERATIONS.md)) against `report_users.csv`, and chase anyone still
   opening the old report.
6. Remove the report from the Power BI app, then delete it and its semantic model, and stop its refresh.

## Tracking progress

Keep a table like this one in your own copy of this file, one row per report:

| Report | Power BI workspace | Dashboard | Status |
|---|---|---|---|
| Sales overview | Sales Reporting | `sales-overview` | Built; reconciled for two months; awaiting owner sign-off |
