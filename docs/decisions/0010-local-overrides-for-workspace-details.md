# 0010. Workspace details in gitignored local files

- **Status:** Accepted
- **Date:** 2026-11-17
- **Links:** pull request "Local overrides for workspace details"

## Context
To deploy, `databricks.yml` and `src/environments.yml` need real workspace hosts and a warehouse id. In a public
repository, or a fork shared with others, people don't want those in git. `workspace.host` can't come from a bundle
variable, and the CLI refuses to deploy when the profile's host and the bundle's host differ, so `--var` alone isn't
enough.

## Decision
Two optional, gitignored files (`*.local.yml` in `.gitignore`):
- `databricks.local.yml` at the repository root, picked up by `include: ["*.local.yml"]` in `databricks.yml`. It
  overrides targets, for example the dev `workspace.host`, `warehouse_id` and `viewers_group`.
- `src/environments.local.yml`, read by `portal/settings.py` (`with_local_hosts`). It sets the `host` of known
  environments only; an unknown environment name stops the app with an error. It is uploaded with the app through
  `sync.include`, like `src/sources_map.json`.

Without the files, nothing changes.

## Why
- Hosts and ids stay out of git without editing committed files that are then easy to commit by accident.
- The bundle's own `include` merge does the work for `databricks.yml`; the app needs a few lines because
  `environments.yml` is read by the app, not the bundle.

## Limitations
- The files are gitignored, so a checkout in CI doesn't have them. The GitHub Actions deploy writes both from the
  GitHub environment's `DATABRICKS_HOST` and `DATABRICKS_WAREHOUSE_ID` just before `bundle validate`
  (`.github/workflows/deploy.yml`), so that workspace stays out of git too. The Azure DevOps pipeline still uses
  committed values or its own variables (`DATABRICKS_HOST`).
- `bundle validate` warns that `src/environments.local.yml` matches no files when it isn't there (as it does for
  `src/sources_map.json`).
- Only hosts can be overridden in `environments.local.yml`, not catalogs, sections or brand.

## Update 2026-11-26: the host is a GitHub secret
Actions logs of a public repository are public, and GitHub masks secrets but not variables: a failed deploy printed
the workspace host in its log. The deploy now reads `DATABRICKS_HOST` from the environment's secrets, falling back to
a variable of the same name so environments not yet moved keep deploying. The setup step also masks the stripped
host and its bare form (no scheme or slash, lower case, as written to `src/environments.local.yml`), because GitHub
masks a secret only as stored. Not covered: IDs that Databricks puts in its own error messages, such as the
workspace id and a principal's user id, which no mask set in advance can match. Only a private repository hides those.

## Alternatives considered
- Uncommitted edits to the committed files (`git update-index --skip-worktree`): hidden state, and easy to commit.
- A literal `include: [databricks.local.yml]`: the bundle fails when the file is missing.
- Setting `PORTAL_ENV` per target: `app.yaml` is shared by every target, so it can't differ per environment.

## Changing it later
Remove the `*.local.yml` include and the `sync.include` line in `databricks.yml`, and `with_local_hosts` in
`src/portal/settings.py`.

## Links
README "Keep your workspace out of git"; `databricks.yml`; `src/portal/settings.py`.
