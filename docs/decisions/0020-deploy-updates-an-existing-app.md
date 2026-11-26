# 0020. Deploy updates an app that already exists

- **Status:** Accepted
- **Date:** 2026-11-26
- **Links:** pull request "Deploy updates an app that already exists"

## Context
Each target's `root_path` in `databricks.yml` is under `/Workspace/Users/${workspace.current_user.userName}/`, so
every identity that deploys keeps its own bundle state. An app created by hand, or deployed by a person from a
laptop, is unknown to the CI service principal's state. The first CI deploy then tries to create it and fails:
`cannot create resources.apps.portal ... HTTP 409 ... ALREADY_EXISTS`, and the permissions resource fails after it.
App names are unique in a workspace, so the deploy can't go on until the app is bound to the bundle. Until now that
was a manual step (OPERATIONS.md, "First CI deploy to an app that already exists").

## Decision
Both pipelines deploy through `scripts/deploy_bundle.sh <target>`. It runs `databricks bundle deploy`. If that
fails, and only when the output names `resources.apps.portal` and `ALREADY_EXISTS`, it reads the app name from
`bundle validate`, runs `databricks bundle deployment bind portal <name> --auto-approve` and deploys again. Any other
failure fails the step with the original exit code. If the bind fails, the step fails and says the deploying
identity needs CAN MANAGE on the app.

## Why
- A deploy to an app that exists should update it, not stop the promotion from dev to test to prod.
- It reacts to one exact error, so real failures are not hidden or retried.
- The name comes from the bundle, so it only ever binds the app the bundle itself declares.

## Limitations
- Binding hands the app to the CI service principal's bundle state. From then on the bundle's settings win: its
  description, resources, scopes and `permissions` replace what was set by hand. Grants on the app that the bundle
  doesn't declare may be removed; add them to `resources/portal.app.yml` or the target in `databricks.yml` first.
- If a person also deploys the same target from a laptop, two bundle states manage one app. Their deploys overwrite
  each other, and a `bundle destroy` from either deletes the app. Give local deploys their own `app_name` in
  `databricks.local.yml` (decision 0010).
- The match is on CLI error text. A CLI upgrade that rewords it turns this back into a plain failure, never a wrong
  bind. `tests/test_deploy_bundle.py` keeps the text the CLI printed.
- The deploying identity needs CAN MANAGE on the existing app (workspace admins have it).

## Alternatives considered
- A shared `root_path` (for example `/Workspace/Shared/.bundle/...`) so people and CI share one state: fixes the cause
  for new deploys, but needs folder permissions for every deployer and still leaves today's hand-made apps unbound.
- Bind before every deploy: needs to know whether the app is already in state, which the CLI doesn't expose
  consistently across versions; a failed bind would also fail healthy deploys.
- Delete the existing app and let the bundle recreate it: loses the app's URL, service principal and grants.
- Keep the manual bind: it blocks every first promotion to a new environment on a person with the CI credentials.

## Changing it later
Replace `bash scripts/deploy_bundle.sh` with `databricks bundle deploy -t <target>` in `.github/workflows/deploy.yml`
and `pipelines/deploy-steps.yml`, and delete the script and its test.

## Links
`scripts/deploy_bundle.sh`; `tests/test_deploy_bundle.py`; OPERATIONS.md "First CI deploy to an app that already
exists"; decision 0010.
