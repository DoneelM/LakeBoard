# 0005. Dev and test apps stopped after every deploy; prod stopped in the evening

- **Status:** Accepted

## Context
A Databricks App bills while it runs. Dev and test are used only when someone is testing. Prod is used in business
hours.

## Decision
- **Dev and test:** the deploy pipeline starts the app with the new code, then stops it again. The stop step always
  runs (`if: always()` in `.github/workflows/deploy.yml`, `condition: always()` in `pipelines/deploy-steps.yml`), so
  a failed start does not leave compute running. It retries five times, 20 seconds apart, and fails the run if the
  app still won't stop. A manual run with "keep running" skips it.
- The stop step passes `-t <target>`. Inside the bundle folder the CLI uses the bundle's default target (dev) for
  non-bundle commands, so without it a test deploy looks for the test app in the dev workspace, fails, and leaves
  test running.
- **Prod:** stop it on an evening schedule. For example, a scheduled Databricks job at 18:00 in your time zone,
  Monday to Friday, that runs `databricks apps stop lakeboard` (or the Apps API) as a principal with
  `CAN_MANAGE` on the app. The job is not part of this repository; create it in the prod workspace.

## Why
- Dev and test cost nothing between tests.
- Prod costs nothing overnight, when nobody uses it.

## Limitations
- Nothing starts prod in the morning. The first person to open the portal starts the app and waits, and warming
  (see 0003) only runs once it is up.
- Anyone testing in dev or test must start the app themselves
  (`databricks -p <your-profile> apps start lakeboard-dev`), and it stays up until stopped or the next deploy.
- Stopping empties the in-memory cache.
- The evening stop is outside the repository, so it is easy to forget when the app is renamed.

## One deploy at a time per environment

Two merges to `develop` close together start two pipeline runs. Without a lock they race: one fails on the bundle
deploy lock, and the other's always-run stop step stops the app while the first run is starting it.

So deploys to one environment run one at a time:

- GitHub Actions: the deploy job has `concurrency: group: deploy-<branch>` with `cancel-in-progress: false`. A second
  run for the same branch waits for the first, then deploys its own commit.
- Azure DevOps: each deploy stage (`DeployDev`, `DeployTest`, `DeployProd`) has `lockBehavior: sequential`. A stage
  with an ID and a `lockBehavior` gets an exclusive lock created automatically, with nothing to set up in the UI,
  and `sequential` makes every run take the lock in turn. The Validate stage is not locked, so checks still run in
  parallel.

This covers any run that reaches the same deploy job or stage, manual runs included. It does not cover:

- Runs for different environments (`develop` and `release`): they run in parallel, which is fine because they touch
  different workspaces (or different apps).
- Pull request runs: they only run checks, which touch nothing live.
- A deploy started from outside the pipeline (someone running `databricks bundle deploy` or stopping the app by
  hand, or the evening stop job).
- Runs are queued, not merged: two merges still give two deploys, one after the other. The later one ends with the
  latest code.

Rejected for Azure DevOps: CI trigger `batch: true` alone (it only holds back CI-triggered runs of a branch, so a
manual run can still overlap); a deployment job with `environment:` and an Exclusive Lock check (a person must
create the environment and the check in the UI); `lockBehavior: runLatest` (the default; it cancels the older
waiting run, which is only right when every run contains all earlier changes, and hides a run from the history).
For GitHub Actions, `cancel-in-progress: true` is rejected for the same reason.

## Alternatives considered
- **Leave every app running.** Simplest, but bills all day in three workspaces.
- **Stop dev and test on a schedule, as in prod.** They would run from each deploy until the evening, when
  usually nobody is testing.

## Changing it later
The dev/test stop step is in `.github/workflows/deploy.yml` and `pipelines/deploy-steps.yml`; the "keep running"
inputs are in the workflow's `workflow_dispatch` inputs and in `azure-pipelines.yml`. The prod schedule lives in
the job you create in the prod workspace. A morning start would be a second scheduled job.

## Links
- [OPERATIONS.md](../OPERATIONS.md) "Starting and stopping (cost)"; [PROMOTION.md](../PROMOTION.md) "What the
  pipeline does"
- `.github/workflows/deploy.yml`, `pipelines/deploy-steps.yml`, `azure-pipelines.yml`
