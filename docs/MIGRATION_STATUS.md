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
- Name review of all tracked files completed (evidence below): one real
  customer name found in a test docstring and replaced with generic wording.
- Residual historical comments referencing the predecessor's internal process
  (audit labels, operator notes, design-doc citations, ticket/decision codes,
  work-package and spec-item references, internal version markers) cleaned from
  comments/docstrings/test titles across the tree, in three reviewed passes.

## Validation at restart point
- `ruff check backend tests` — pass
- `pytest -q` — 2699 passed, 2 skipped
- frontend `lint`, `typecheck`, `test` (840 passed), `build` — pass
- `scripts/ci/check_frontend_classes.py`, repo hygiene, commit-message check — pass
- gitleaks over full history — no leaks

## Review evidence (name review, restart session)
- Name-list cross-reference: a fresh extraction from the archived data CSVs
  (customer companies, employee names, emails) was matched against every
  tracked file (full-name, two-word-tail, person-name, and email forms).
  The single real-customer match (a test docstring) was replaced; all other
  matches were generic terms, public product names (OpenShift, Ansible), or a
  public distributor name in a NetSuite header fixture.
- Synthetic-data checks: every email domain in tracked files is synthetic
  (example/.test/.local); no tracked data files (.db/.csv/.xlsx); no real
  internal domains, account IDs, or territory codes; no predecessor-company
  identity references.
- Owner flag (optional): one synthetic stakeholder persona in a mocked-LLM
  test payload (tests/backend/test_knowledge_enrichment.py). The name does not
  appear in the archived data; rename if the owner prefers an unmistakably
  placeholder name.
- Deliberately left unchanged (no privacy content, cosmetic call for the
  owner): internal feature codes inside test FILE names and suite ids
  (Part14*, U4Navigation, F10F12, H1/H2, test_part13_dv_wave2.py,
  test_arch_rerecon_a7.py) and a few synthetic fixture values that embed
  work-package codes (e.g. "WP3Co").

## Remaining (priority order)
1. Owner's final human review pass (agent review above states its coverage and
   limits; private name lists remain in `.private-migration/`).
2. Add GitHub repository secret `SAIL_DENYLIST` (brand/identity regexes;
   the local git-ignored `.denylist` is ready —
   `gh secret set SAIL_DENYLIST --body-from .denylist`).
3. Choose a license (recommendation: Apache-2.0; MIT also fine).
4. Decide on optional integrations kept in code: LDAP/AD directory auth,
   Azure Document Intelligence provider, NetSuite/RVTools/Red Hat import
   panes. Recommendation: keep all (generic, config-gated; the import panes
   are core product value). If trimming, drop LDAP first.
5. Push only when the user authorizes it (local is ahead of origin).
