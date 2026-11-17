# 0002. Queries run as the viewer; `auth: app` is the exception

- **Status:** Accepted

## Context
Who may see which rows is already set in Unity Catalog: grants, row filters and column masks. We did not want each
dashboard to repeat those rules. Some users, such as field staff who use one operational dashboard, have no Unity
Catalog access of their own but still need that dashboard.

## Decision
- The app uses on-behalf-of user auth. `resources/portal.app.yml` asks for the `sql` and `genie` user scopes, and
  each dataset query runs with the viewer's own token (`x-forwarded-access-token`).
- So Unity Catalog grants, row filters and masks always apply, whatever the page does.
- A dataset can set `auth: app`. It then runs as the app's service principal, and one result is shared by everyone.
  This is for people with no data access.
- `scripts/grant_app_access.py` prints (and with `--apply` runs) the grants the service principal needs for the
  `auth: app` and warmed datasets in an environment.

## Why
- One place for data security: Unity Catalog. A page bug can't show rows a person isn't allowed to see.
- Query history shows the real person, not the app.
- `auth: app` lets us serve a dashboard to people we don't want to give table access to.

## Limitations
- Every viewer needs Unity Catalog access (`USE CATALOG`, `USE SCHEMA`, `SELECT`) to every view a default dataset
  reads. Missing grants show as "Couldn't load this data".
- `auth: app` datasets cannot take parameters (the checks reject them) and bypass row-level security. Use it only
  for data that everyone who can open the dashboard may see.
- A dashboard with `auth: app` data cannot have Ask Genie (see 0006).
- Each environment's app has its own service principal, and each needs the grants. The script also grants
  `SELECT, MODIFY` on the usage table where one is set. A view that is dropped and recreated loses its grants, so
  run the script again.

## Alternatives considered
- **Everything as the app's service principal.** Simple, but every viewer would see whatever the app can read and
  row filters would stop applying.
- **Security rules in each page or SQL file.** Duplicates Unity Catalog and is easy to get wrong.

## Changing it later
`auth:` is per dataset in `dashboard.yml`. Switching a dataset to `auth: app` needs the grant script run in every
environment first. The scopes are in `resources/portal.app.yml`.

## Links
- [DESIGN.md](../DESIGN.md) "Security model"; [OPERATIONS.md](../OPERATIONS.md) "Access" and "How data refreshes"
- `src/portal/auth.py`, `src/portal/registry.py`, `resources/portal.app.yml`, `scripts/grant_app_access.py`
