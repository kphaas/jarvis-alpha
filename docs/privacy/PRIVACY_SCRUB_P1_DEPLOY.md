# Privacy-Scrub P1 Review And Deploy Notes

## Scope

P1 is additive and inert:

- New package: `brain/agents/privacy_scrub/`
- New migration: `brain/db/migrations/20260605_010000_privacy_scrub_foundations.sql`
- New tests: `tests/test_privacy_scrub_*.py`
- New ADR: `docs/adr/ADR-0015-privacy-scrub-alpha-placement.md`

No runner is wired into Buddy. No HTTP route or executor is active.

## Verify

Run from the Alpha repo:

```bash
ruff check brain/agents/privacy_scrub tests/test_privacy_scrub_*.py
ruff format --check brain/agents/privacy_scrub tests/test_privacy_scrub_*.py
pytest tests/test_privacy_scrub_subjects.py -v
pytest tests/test_privacy_scrub_identity.py -v
pytest tests/test_privacy_scrub_targets.py -v
pytest tests/test_privacy_scrub_policy.py -v
pytest tests/test_privacy_scrub_schema.py -v
```

The DB integration portions of `tests/test_privacy_scrub_schema.py` require a
throwaway Postgres database:

```bash
TEST_PG_DSN='postgresql://localhost/jarvis_alpha_test' \
  pytest tests/test_privacy_scrub_schema.py -v
```

## Migration

Apply only through the canonical Alpha migration runner on Brain:

```bash
bash ~/jarvis-alpha/scripts/apply_migrations.sh
```

Do not manually run the SQL against production unless Ken explicitly approves a
break-glass path.

## Secrets

P1 does not consume a runtime secret. Do not seed `PRIVACY_SCRUB_*` secrets
until P2 adds a caller that needs encryption or digest keys.

## Rollback

Pre-merge rollback is branch deletion only. Post-merge rollback should be a
normal `git revert` plus a reviewed forward migration if schema removal is
required. Do not run table-dropping SQL without explicit confirmation.
