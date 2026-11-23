# 0018. Publishing guards: reviewed pages, reviewed shared SQL, groups for app data, credential-free PR checks

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
LakeBoard is designed so that business authors and coding agents can write dashboards. That makes four things
worth guarding explicitly:
- A dashboard's page is JavaScript that runs in the portal's own origin, next to every other dashboard.
- A `cache: shared` result (and every warmed one) is fetched once and served to every permitted viewer. That is only
  safe when the SQL and its views return the same rows for everyone.
- An `auth: app` dataset is read as the app's service principal, so Unity Catalog no longer narrows it per viewer.
  With `groups: []` it would be readable by everyone who can open the portal.
- Pull request pipelines that hold workspace credentials can be edited by the pull request itself.

## Decision
- **Reviewed pages.** Each dashboard's `index.html` must match its SHA-256 in `src/reviewed_pages.yml` (key: the
  slug). For `page: artifact`, each file in `assets/` must also match (key: `<slug>/assets/<file>`). The digest is
  of the UTF-8 text with LF line endings (images and fonts: raw bytes), so CRLF checkouts agree.
- **Reviewed shared SQL.** Each `auth: user` dataset with `cache: shared` (warming needs `cache: shared`) must match
  the SHA-256 of its SQL file in `src/shared_cache.yml` (key: `<slug>/<dataset>`). `todo` datasets are exempt until
  they have SQL. The page approval and the SQL approval are independent: changing one doesn't invalidate the other.
- **Explicit groups for `auth: app`.** The registry refuses an `auth: app` dataset unless both the dashboard and the
  dataset list `groups:`.
- The registry enforces the approvals for folders under `src/dashboards/`, so `check.py --static`, the tests and the
  app all refuse an unreviewed dashboard. A missing approval file approves nothing; a malformed one stops loading.
  A developer's local run (`run_local.*`) still shows unreviewed work, with a warning, so authors can preview; a
  deployed app never does.
- `scripts/approve.py <slug> [--write]` prints or records the digests. The reviewer runs it in the same pull request.
- **Credential-free PR checks.** In `azure-pipelines.yml` the Validate stage no longer uses the service connection
  or a variable group; `bundle validate` moved to the deploy stages, which also skip PR builds explicitly. The
  GitHub workflow already kept secrets in the deploy job; its check job is documented as credential-free.
- **Pinned CLI.** Both pipelines install a pinned Databricks CLI release and check its SHA-256 before installing it
  and before requesting a credential, instead of piping a moving installer script into bash.
- The cached identity (user and groups) now lives 60 seconds instead of 600, and its key is a SHA-256 of the whole
  forwarded token rather than its last 24 characters.

## Why
- Executable HTML is the largest thing an author can change. A digest ties a merge to the exact code someone read.
- Whether shared SQL is viewer-independent can't be decided by a parser; it needs a person who knows the views.
- App-identity reads bypass per-viewer Unity Catalog checks, so their audience must be stated, never defaulted.
- Credentials in PR builds are reachable by whoever can open a PR that edits the pipeline.

## Limitations
- A digest records that a version was approved, not that the review was good. Approved JavaScript still runs in the
  portal origin. Running untrusted scripts would need an isolated origin or frame and a narrow data broker.
- The approval files and `src/static/` (shared JavaScript) need reviewer enforcement outside the repository:
  CODEOWNERS or branch-policy required reviewers. Without it an author could approve their own page.
- Repository YAML can't govern edits to a PR pipeline. On Azure DevOps, restrict the service connection and variable
  groups with pipeline permissions and branch checks; on GitHub, keep secrets in environments limited to the
  deploy branches.
- The CLI archive is pinned; Python dependencies are not locked here, and there is no SBOM or vulnerability scan.
  Upgrading the CLI means changing the version and its checksum in both pipelines.
- A one-minute identity cache still lets a removed member act for up to a minute, plus Databricks propagation time.
- A sample-dashboard change now also updates two approval files, a small extra step for contributors.

## Alternatives considered
- Reviewing pages by convention only: nothing stops an unreviewed edit from merging and deploying.
- Approving whole dashboards by commit hash: brittle under rebases and merges, and not tied to the file content.
- Parsing SQL to decide whether it is viewer-independent: row filters and masks live on the views, not in the SQL.
- Removing `auth: app`: it is the only way to show data to people with no direct access, which some dashboards need.
- Keeping `bundle validate` in PR builds: useful, but it needs workspace credentials in a PR context.

## Changing it later
`load_approvals`, `digest` and the checks are in `src/portal/registry.py`; `blocking_errors` in `src/app.py` decides
what a local run may show; the identity cache is `_IDENTITY_TTL` in `src/portal/auth.py`; the CLI version and
checksum are in `pipelines/deploy-steps.yml` and `.github/workflows/deploy.yml`.

## Links
- [docs/AUTHORING.md](../AUTHORING.md) (step 5, reviews), [docs/OPERATIONS.md](../OPERATIONS.md) (Access),
  [docs/PROMOTION.md](../PROMOTION.md) (pipeline and one-off setup)
- Related: [0002](0002-queries-run-as-the-viewer.md) (`auth: app`), [0003](0003-caching-and-warming.md) (shared
  cache), [0011](0011-claude-dashboard-artifacts.md) (artifact pages), [0013](0013-platform-reliability.md)
  (shared-result access check)
