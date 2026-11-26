## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] Decision record added or updated in `docs/decisions` (for a design change)
- [ ] Tests and `scripts/check.py --static` pass
- [ ] A changed page or `cache: shared` SQL was reviewed by the data team, and its digests recorded with
      `python scripts/approve.py <slug> --write` (`docs/AUTHORING.md`, step 5)
- [ ] No company data, workspace hosts, warehouse IDs or tokens (see `CONTRIBUTING.md`)
- [ ] Docs updated if behaviour changed (`docs/`, the dashboard's `README.md`)
- [ ] Every dataset is a SQL file in `sql/` (no numbers fetched by asking Genie), and the dashboard's
      `README.md` reconciles its numbers against a trusted report (`docs/BUSINESS_AUTHORS.md`)
- [ ] Access (`groups`), `auth: app` and `cache: shared` / `warm` changes are called out for the data team
