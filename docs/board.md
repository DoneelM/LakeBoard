# Task board

Open LakeBoard work: its branch, pull request, task and owner. Each PR's state (review, QA, merged) is on GitHub, so it isn't tracked here.

| Branch | PR | Task | Owner |
|---|---|---|---|
| `fix/csv-injection` | [#27](https://github.com/DoneelM/LakeBoard/pull/27) | CSV export: neutralise formula cells; Node tests for csv, fmt and h() | Black Widow |
| `fix/self-host-fonts-csp` | [#28](https://github.com/DoneelM/LakeBoard/pull/28) | Self-host Inter, drop Google font hosts from the CSP, add `frame-ancestors 'self'` | Black Widow |
| `test/playwright-smoke` | [#29](https://github.com/DoneelM/LakeBoard/pull/29) | Playwright smoke test of the local app with stubbed data | Black Widow |
| `fix/deploy-workflow` | [#30](https://github.com/DoneelM/LakeBoard/pull/30) | Fail when `DATABRICKS_HOST` is missing on this repo; `id-token: write` on the deploy job only; pin Actions | Hulk |
| `fix/dev-target-from-env` | [#32](https://github.com/DoneelM/LakeBoard/pull/32) | CI deploys develop from GitHub environment vars; workspace stays out of git; leave lakeboard-dev running | Hulk |
| `docs/adr-fail-closed-host` | [#33](https://github.com/DoneelM/LakeBoard/pull/33) | Decision 0019: fail closed when the workspace host is unmatched or, in a deployed app, empty | Hulk |
| `fix/identity-cache-lock` | [#35](https://github.com/DoneelM/LakeBoard/pull/35) | One lock around every identity-cache read and write; Databricks lookup outside it | Black Widow |
| TBD | — | Host resolution follow-ups (Wolverine #31 L1/I1-I3) | Hulk |

## Standing permissions

Permissions Doneel has given the team once, so agents don't ask again. None granted yet; add each with its date.
