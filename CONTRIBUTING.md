# Contributing to LakeBoard

Thanks for helping. Bug reports, docs fixes, new sample dashboards and framework changes are all welcome.

## Before you start

- **Small fixes** (typos, docs, an obvious bug): open a pull request straight away.
- **Bigger changes** (a new feature, a change to `dashboard.yml` or the `dash` API): open an issue first, so we can
  agree the approach before you write the code.
- **Security problems:** don't open a public issue. Use GitHub's "Report a vulnerability" on the Security tab.

## Making a change

1. Fork the repo and create a branch from `main`.
2. Make the change. Keep the style of the code and docs around it: short functions, short plain sentences.
3. Run the checks. They need no Databricks workspace:

   ```bash
   python -m pip install -r src/requirements.txt pytest
   python -m pytest -q
   PORTAL_ENV=dev python -m pytest -q
   python scripts/check.py --static
   ```

4. If you changed a sample dashboard's SQL, run it against a workspace you own
   (Databricks Free Edition works):
   `python scripts/check.py --profile <your-profile> --warehouse <warehouse-id>`.
5. Open a pull request into `main` and fill in the template.

The `develop` → `release` → `main` flow in [docs/PROMOTION.md](docs/PROMOTION.md) is for teams deploying LakeBoard
to their own workspaces. Contributions to this repo go straight to `main`.

## What a good pull request has

- **One change.** Two unrelated fixes are two pull requests.
- **Tests** for new behaviour, in `tests/`. Tests must pass in any environment (see [AGENTS.md](AGENTS.md)).
- **Reviews recorded** for a new or changed sample page or `cache: shared` SQL: `python scripts/approve.py <slug>
  --write` updates `src/reviewed_pages.yml` and `src/shared_cache.yml` (see [docs/AUTHORING.md](docs/AUTHORING.md)).
- **A decision record** in [docs/decisions/](docs/decisions/README.md) for a design change: what, why, the
  alternatives, and the limits.
- **No company data.** Sample dashboards read only the built-in `samples` catalog. Never commit workspace hosts,
  warehouse IDs, tokens, people's names or real business data.

## AI-assisted contributions

Welcome. Dashboards here are designed to be written by AI coding tools. [AGENTS.md](AGENTS.md) has the rules they
should follow. [docs/DASHBOARD_WORKFLOW.md](docs/DASHBOARD_WORKFLOW.md) is the shared workflow for all
agents; keep tool-specific entry points as links to it. You are still responsible for what you submit: read it
and run the checks.

## Licence of contributions

LakeBoard is licensed under the [Apache License 2.0](LICENSE). By submitting a pull request you agree that your
contribution is licensed under the same terms (section 5 of the licence). No separate agreement is needed.

## Code of conduct

Be kind and assume good intent. Critique the code, not the person. The maintainer may remove comments, issues or
pull requests that don't follow this.
