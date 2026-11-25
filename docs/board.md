# Task board

Open LakeBoard work, its branch and pull request. Update the row in the same PR that changes the status.

| Branch | PR | Task | Owner | Status |
|---|---|---|---|---|
| `chore/review-gate-codeowners` | [#23](https://github.com/DoneelM/LakeBoard/pull/23) | CODEOWNERS for the review gate and shared static files; this board | Hulk | changes requested |
| `chore/tidy` | [#24](https://github.com/DoneelM/LakeBoard/pull/24) | Remove `catalogue_entry`; merge the duplicate `AGENTS.md` bullets; renumber decision 0012 | Hulk | approved, in QA |
| `test/approve-check-ruff` | [#25](https://github.com/DoneelM/LakeBoard/pull/25) | Tests for `approve.py` and `check.py`; ruff (F, E9, B) and its 12 findings | Hulk | approved, in QA |
| `fix/auth-cache-eviction` | [#26](https://github.com/DoneelM/LakeBoard/pull/26) | Evict expired identities; drop locks for evicted cache keys; fail start-up on an unmatched host | Hulk | in review |
| `fix/deploy-workflow` | not opened | Fail when `DATABRICKS_HOST` is missing on this repo; `id-token: write` on the deploy job only; pin Actions; add `ruff check` | Hulk | blocked: push needs the `workflow` token scope |

## Standing permissions

Permissions Doneel has given the team once, so agents don't ask again. None granted yet; add each with its date.
