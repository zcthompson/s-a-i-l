# Migration status — restart point

Restart point tag: `restart/hermes-01` (local). Read `AGENTS.md` first.
Private working notes live in the ignored `.private-migration/HANDOFF.md`.

## Done (v0.0.1)
- Guardrails: CI (hygiene, commit-message attribution check, gitleaks,
  backend/postgres/frontend/container jobs), git hooks (`sh scripts/setup-hooks.sh`).
- Backend, migrations, scripts, tests migrated and renamed (S-A-I-L, `SAIL_*` env).
- Frontend migrated with new logo/favicon and navy/ocean/teal palette.
- Real-data seed importers and organization/customer/branch/personal data removed;
  demo seed is fictional; customers are created in-app or via user-supplied CSV.
- Placeholder-only `.env.example`; README rewritten.

## Validation at restart point
- `ruff check backend tests` — pass
- `pytest -q` — 2699 passed, 2 skipped
- frontend `lint`, `typecheck`, `test` (840 passed), `build` — pass
- `scripts/ci/check_frontend_classes.py`, repo hygiene, commit-message check — pass
- gitleaks over full history — no leaks

## Remaining (priority order)
1. Human review of all tracked files for residual real person/customer names
   (automated lists are known to be incomplete).
2. Add GitHub repository secret `SAIL_DENYLIST` (brand/identity regexes).
3. Choose a license.
4. Decide on optional integrations kept in code (LDAP auth, Azure document
   provider, vendor-specific import panes); Azure deploy assets were dropped.
5. Clean residual historical comments referencing the predecessor's process
   (dates, "operator directive" notes) where they add no value.
6. Push only when the user authorizes it.
