# 0004. Promotion: the same branch to each environment

- **Status:** Accepted

## Context
`develop`, `release` and `main` deploy to dev, test and prod (`.github/workflows/deploy.yml` or
`azure-pipelines.yml`). Several changes can be in flight on `develop` at once. We needed a way to move one change
to test and prod without carrying other people's unfinished work, and without cherry-picking every commit.

## Decision
- Branch from `main`, not `develop`.
- Open a pull request from the **same** feature branch into `develop`, then `release`, then `main`. Never let prod
  get a change before test.
- Never merge `develop` into a feature branch. If the pull request into `develop` conflicts, resolve it on a
  throwaway `<feature>-into-develop` branch and open that into `develop`. The `release` and `main` pull requests
  still come from the clean feature branch.
- Cherry-pick only as a fallback (hotfixes), with `git cherry-pick -x` and one pull request per target branch.
- Keep dependent changes on one branch.

The steps are in [PROMOTION.md](../PROMOTION.md).

Example: a release that carries a new dashboard and a fix to another one can be built by merging the original
feature branches into one promotion branch, with no cherry-picks, and opening that into `release` and then `main`.

## Why
- Each environment gets identical commits, so what was tested is what reaches prod.
- A merge only applies the branch's own changes, so in-flight work on `develop` never rides along.

## Limitations
- It needs discipline. One merge of `develop` into a feature branch carries unreleased work into the test and prod
  pull requests.
- A change that depends on work that exists only on `develop` cannot be promoted until that work is.
- The branches end up with identical files but different merge commits, so the ahead/behind counts your git host
  shows never reach zero. Compare files instead: `git diff --stat origin/main origin/develop`.
- Three pull requests per change means more reviews and more pipeline runs.

## Alternatives considered
- **Promote `develop` to `release` to `main` as whole branches.** Simple, but releases everything on `develop`,
  ready or not.
- **Cherry-pick each change.** Works, but commits differ by hash between branches and are easy to miss or reorder.

## Changing it later
Prefer config switches (`environments:` in `dashboard.yml`) to keep unfinished work off in higher environments,
rather than keeping it off the branch. Any change to the branch model needs a new record and an update to
PROMOTION.md.

## Links
- [PROMOTION.md](../PROMOTION.md); `.github/workflows/deploy.yml`, `azure-pipelines.yml`
