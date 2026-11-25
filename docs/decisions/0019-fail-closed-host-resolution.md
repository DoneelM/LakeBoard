# 0019. Fail closed when the workspace host is unmatched or, in a deployed app, empty

- **Status:** In progress
- **Links:** [pull request #26](https://github.com/DoneelM/LakeBoard/pull/26) (unmatched host; pending), [pull request #31](https://github.com/DoneelM/LakeBoard/pull/31) (empty host when deployed; pending)

## Context
`current_env()` in `src/portal/settings.py` picks the environment that drives catalog swaps. It uses `PORTAL_ENV` if
that is set, otherwise the environment whose host in `src/environments.yml` (after `environments.local.yml`) matches
`DATABRICKS_HOST`. Until #26, a host that matched nothing, or a blank host, fell through to prod. In a deployed app
that meant a typo, a missing `environments.local.yml`, or a blank `DATABRICKS_HOST` could silently read prod catalogs.

## Decision
- `PORTAL_ENV`, when set to a known environment name, still wins.
- Otherwise the host must match an environment. An unmatched host raises at start-up (#26).
- A blank host in a deployed app also raises (#31). `is_deployed()` is true when any of `DATABRICKS_APP_NAME`,
  `DATABRICKS_APP_URL` or `DATABRICKS_APP_PORT` is set, which Databricks Apps always does. Databricks Apps also
  always sets `DATABRICKS_HOST`, so a blank host when deployed is a misconfiguration and must not read prod.
- A local run with a blank host and no `PORTAL_ENV` still resolves to prod. That is a known follow-up.

## Why
A silent fallback to prod in a running app is the wrong catalogs, not a noisy start-up error. Failing closed makes
the misconfiguration obvious.

## Limitations
- `PORTAL_ENV` still skips the host checks. That is intentional when every environment shares one workspace.
- A local run with a blank host still becomes prod. Changing that is a follow-up, not part of #26 or #31.
- Until #26 and #31 merge, a deployed app can still fall through to prod.

## Alternatives considered
- Keep the prod fallback. Rejected: a typo or a missing local file would read prod without a signal.
- Require `PORTAL_ENV` in every app. Rejected: host matching already works when the hosts in `environments.yml` or
  `environments.local.yml` are correct, and `app.yaml` cannot set a different `PORTAL_ENV` per target (decision 0010).
- Fail on a blank host in local runs too. Deferred: local `run_local.*` often has no host, and today that means prod.

## Changing it later
The rule is `current_env()` in `src/portal/settings.py`. The tests are in `tests/test_eviction.py`. The start-up
errors are also listed in `docs/OPERATIONS.md` and in the header of `src/environments.yml`.

## Links
`src/portal/settings.py`, `src/environments.yml`, `docs/OPERATIONS.md` "When something goes wrong".
