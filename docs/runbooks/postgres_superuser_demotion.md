# Postgres Superuser Demotion Runbook

## Purpose

Close the last RLS integrity gap by removing `SUPERUSER` from `jarvisbrain`
without losing emergency cluster recovery.

`jarvisbrain` currently owns the `jarvis_alpha` database and public schema
objects. Ownership allows normal DDL on owned objects, but `SUPERUSER` lets any
`jarvisbrain` session bypass FORCE RLS. Runtime app traffic uses
`jarvis_alpha_writer`, so the risk is operator, migration, or ad-hoc sessions.

## Hard Stop

Do not run:

```sql
ALTER ROLE jarvisbrain NOSUPERUSER;
```

until all gates below are true.

## Gates

1. A separate break-glass superuser exists, can login locally on Brain, and its
   credential is stored outside the app secrets path.
2. `jarvis_alpha_writer` and `jarvis_alpha_app` are `NOSUPERUSER` and
   `NOBYPASSRLS`.
3. The migration runner has been checked for data-DML migrations on FORCE RLS
   tables. Any required backfill must either set an explicit `platform_admin`
   RLS context or use a reviewed SECURITY DEFINER function.
4. Porchlight `postgres_role_safety` is deployed and expected to fail before
   demotion, then pass after demotion.
5. A rollback path is written down and tested with the break-glass identity:

```sql
ALTER ROLE jarvisbrain SUPERUSER CREATEDB CREATEROLE;
```

## Target End State

```text
jarvisbrain          NOSUPERUSER NOBYPASSRLS CREATEDB CREATEROLE
jarvis_alpha_writer  NOSUPERUSER NOBYPASSRLS
jarvis_alpha_app     NOSUPERUSER NOBYPASSRLS
break-glass role     SUPERUSER, local/operator use only
```

## Verification

```sql
SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname IN ('jarvisbrain', 'jarvis_alpha_writer', 'jarvis_alpha_app')
   OR rolsuper
ORDER BY rolname;
```

Expected after demotion:

- `jarvisbrain.rolsuper = false`
- `jarvis_alpha_writer.rolsuper = false`
- `jarvis_alpha_writer.rolbypassrls = false`
- `jarvis_alpha_app.rolsuper = false`
- `jarvis_alpha_app.rolbypassrls = false`
- exactly one reviewed break-glass superuser remains
