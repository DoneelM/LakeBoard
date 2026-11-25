# Task board

Open LakeBoard work: its branch, pull request, task and owner. Each PR's state (review, QA, merged) is on GitHub, so it isn't tracked here.

| Branch | PR | Task | Owner |
|---|---|---|---|
| `chore/review-gate-codeowners` | [#23](https://github.com/DoneelM/LakeBoard/pull/23) | CODEOWNERS for the review gate and shared static files; this board | Hulk |
| `chore/tidy` | [#24](https://github.com/DoneelM/LakeBoard/pull/24) | Remove `catalogue_entry`; merge the duplicate `AGENTS.md` bullets; renumber decision 0012 | Hulk |
| `test/approve-check-ruff` | [#25](https://github.com/DoneelM/LakeBoard/pull/25) | Tests for `approve.py` and `check.py`; ruff (F, E9, B) and its 12 findings | Hulk |
| `fix/auth-cache-eviction` | [#26](https://github.com/DoneelM/LakeBoard/pull/26) | Evict expired identities; drop locks for evicted cache keys; fail start-up on an unmatched host | Hulk |
| `fix/csv-injection` | [#27](https://github.com/DoneelM/LakeBoard/pull/27) | CSV export: neutralise formula cells; Node tests for csv, fmt and h() | Black Widow |
| `fix/self-host-fonts-csp` | [#28](https://github.com/DoneelM/LakeBoard/pull/28) | Self-host Inter, drop Google font hosts from the CSP, add `frame-ancestors 'self'` | Black Widow |
| `test/playwright-smoke` | [#29](https://github.com/DoneelM/LakeBoard/pull/29) | Playwright smoke test of the local app with stubbed data | Black Widow |
| `fix/deploy-workflow` | not opened | Fail when `DATABRICKS_HOST` is missing on this repo; `id-token: write` on the deploy job only; pin Actions | Hulk |

## Standing permissions

Permissions Doneel has given the team once, so agents don't ask again. None granted yet; add each with its date.
