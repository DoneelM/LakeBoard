# Promoting changes: dev → test → prod

Each environment is one long-lived branch, deployed by CI to its own app.

| Branch | Deploys to | Workspace | App | Catalog read (example) |
|---|---|---|---|---|
| `develop` | Dev | your dev workspace | `lakeboard-dev` | `main_dev` (and `samples`) |
| `release` | Test | your test workspace | `lakeboard-test` | `main_test` (and `samples`) |
| `main` | Prod | your prod workspace | `lakeboard` | `main_prod` (and `samples`) |

The workspace hosts and warehouse ids are set per target in `databricks.yml`, and the hosts again under
`environments:` in `src/environments.yml`. The catalog swap is set under `catalogs:` in the same file. All three
can be one workspace (a Databricks Free Edition workspace is enough to try it); then set `PORTAL_ENV` per app.

Two example pipelines do all three, so pick the one for your git host:

- **GitHub Actions:** `.github/workflows/deploy.yml`. It signs in with a service principal's OAuth secret
  (`DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`) or GitHub OIDC, and reads `DATABRICKS_HOST` and
  `DATABRICKS_WAREHOUSE_ID` from the GitHub environment (`dev`, `test` or `prod`). It writes the gitignored
  `databricks.local.yml` and `src/environments.local.yml` from them, so no workspace is committed.
- **Azure DevOps:** `azure-pipelines.yml` with `pipelines/deploy-steps.yml`. It signs in through the
  `databricks-service-connection` service connection and reads `DATABRICKS_HOST` from the `lakeboard-dev-vars`,
  `lakeboard-test-vars` and `lakeboard-prod-vars` variable groups. All of these names are placeholders.

## The steps for one change

1. **Branch from `main`**, not from `develop`: `git switch -c feature/<name> origin/main`.
2. Build and check locally ([AUTHORING.md](AUTHORING.md)).
3. **PR the feature branch into `develop`.** The pipeline runs the checks. Merging deploys to dev.
4. Test in dev. Start the app if it is stopped, then [review the deployment](OPERATIONS.md#review-a-deployment),
   including a dashboard smoke test, Security, and Insights system metrics.
5. **PR the same feature branch into `release`.** Merging deploys to test. The business owner signs off here.
6. **PR the same feature branch into `main`.** Merging deploys to prod. Review the active prod deployment after rollout.

Because the same branch is merged three times, each environment gets identical commits and nothing needs
cherry-picking. A merge only applies that branch's own changes, so other people's unfinished work on `develop`
never rides along to test or prod.

## Rules

- **Never merge `develop` into a feature branch.** If the PR into `develop` conflicts, create
  `<feature>-into-develop` from the feature branch, resolve the conflict there (keep both sides), and PR that
  into `develop`. The PRs into `release` and `main` still come from the clean feature branch.
- **Promote in order.** Prod never gets a change before test.
- **Keep dependent changes on one branch.** If a dashboard needs a new shared feature, both go on the same branch.
- **Cherry-pick only for hotfixes**, with `git cherry-pick -x`, one PR per target branch.

## What the pipeline does

| When | What runs |
|---|---|
| Any PR into `develop`, `release` or `main` | Credential-free checks only: `scripts/check.py --static` (including the page and shared-SQL reviews) and `pytest`. No service connection, variable group or secret is used |
| Push (merge) into one of the three branches | The same checks, then for that environment: install the pinned, checksum-verified Databricks CLI, `bundle validate`, every dataset query with `LIMIT 0` against its catalogs, the source map for the freshness label, `bundle deploy` (updating the app if it already exists, decision 0020), and `bundle run portal` (starts the app with the new code) |
| After a test deploy (and a dev deploy in Azure DevOps) | The app is stopped again to save cost. To keep it up, run the pipeline by hand with "keep running" ticked (`keep_running` in GitHub Actions, "Leave the dev/test app running" in Azure DevOps). In GitHub Actions the dev app (`develop`) and prod always stay running |
| Two runs for the same environment overlap | The second waits until the first has finished, then deploys its own commit (GitHub: a `concurrency` group per environment; Azure DevOps: `lockBehavior: sequential`). Runs for different environments don't wait for each other |

A deployment fails before anything changes if a query refers to a view that doesn't exist yet in that
environment's catalog. Promote the view first.

## Switching a dashboard on per environment

To merge work that isn't ready for everyone, limit where it appears in its `dashboard.yml`:

```yaml
environments: [dev, test]     # hidden in prod until this line is removed
```

Removing the line is a normal change that goes through the same three PRs.

## One-off setup (data team)

- Replace the placeholders: workspace hosts and `warehouse_id` per target and `viewers_group` in `databricks.yml`,
  and the hosts under `environments:` in `src/environments.yml`.
- A service principal for deploys, added to each workspace. It needs permission to create apps, `CAN USE` on the
  SQL warehouse, and `SELECT` on the views the dashboards read (for the `LIMIT 0` check).
- **GitHub:** create the environments `dev`, `test` and `prod` with the `DATABRICKS_HOST` and `DATABRICKS_WAREHOUSE_ID` variables and the client
  id and secret (or an OIDC federation policy). Add required reviewers on `prod` if a person should approve each
  prod deploy.
- **Azure DevOps:** create the pipeline from `azure-pipelines.yml` and authorise it to use the service connection
  and the three variable groups. Restrict them to the protected branches (pipeline permissions and branch control
  checks): a YAML condition can't stop an edited pipeline in a pull request from using them. For Azure Repos, add the
  pipeline as build validation in each branch policy (the `pr:` trigger only applies to GitHub-hosted repos).
- Branch protection (or branch policies) on `develop`, `release` and `main`: require a PR, the checks, and a data
  team reviewer. Make the data team the required reviewers (CODEOWNERS on GitHub, required reviewers by path on
  Azure DevOps) for `src/reviewed_pages.yml`, `src/shared_cache.yml` and `src/static/`, so an author can't approve
  their own page.
- Serverless SQL warehouses are a good fit: they start quickly and stop when idle. A warehouse shared with other
  tools works, but portal queries then queue behind theirs.
- If an app with the same name already exists in a workspace (for example one created by hand), delete it or
  rename the bundle's app before the first pipeline deploy, or the deploy fails because the name is taken.
- After the first deploy, run `scripts/grant_app_access.py` per environment for warmed and `auth: app` datasets
  and the freshness label ([OPERATIONS.md](OPERATIONS.md)).
- Add more groups for prod in `databricks.yml` (commented example under the `prod` target) as dashboards go live.
