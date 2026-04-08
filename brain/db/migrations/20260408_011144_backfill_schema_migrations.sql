-- 20260408_011144_backfill_schema_migrations.sql
-- Backfills schema_migrations with all historical migration files that were
-- applied to Brain BEFORE the tracking table existed (pre April 7 2026).
--
-- Source: 'pre-tracking'  →  applied_at is NULL (we don't know when)
-- Checksums are computed from the file contents on disk at backfill time.
-- These checksums lock the historical files: any future edit to one of these
-- files will cause the runner to refuse to start.
--
-- Skips: this file itself, the create_schema_migrations file, and READMEs.

BEGIN;

INSERT INTO schema_migrations (filename, checksum, applied_at, applied_by, source)
VALUES
  ('003_memory_tiers.sql', '225f27ea8f9c414243f1c5dee0e5b6172851d48937ce34ec88ce54cbabf36d91', NULL, 'backfill', 'pre-tracking'),
  ('004_dev_agent.sql', '9efe39b40a1703c8dddafc25c855d1e707e0ec15d11e72b169e28d15da0623dd', NULL, 'backfill', 'pre-tracking'),
  ('004_vector_768.sql', '245fd58d577a9c94fe23d122c17fd8e69a2ec0f1b45508f126c956afd4bd7375', NULL, 'backfill', 'pre-tracking'),
  ('005_buddy_events.sql', '916fcbbff4f2553a5acce5a8dd5426c1ebe934ca990b15944c658e0c1823f6b8', NULL, 'backfill', 'pre-tracking'),
  ('006_task_graphs.sql', 'ba7d27625180870a21c85e0712305e7841bc221b8d426a8a4e58800e8911bf2d', NULL, 'backfill', 'pre-tracking'),
  ('007_honeypot_events.sql', '36930898bc53e11325ad9dfa9aa4a2e69e8701a47eb26450d06cb5e9ef4b1f25', NULL, 'backfill', 'pre-tracking'),
  ('007_node_registry.sql', '8318afcbd7a862572139e6159d6775a2cb424cfaf674882e3aefdab7fadc2b03', NULL, 'backfill', 'pre-tracking'),
  ('007_prompt_registry.sql', '0eebae23f6e92eb9e11b904d6063649e63c7bf151e557a4153e35f7bdeaa108d', NULL, 'backfill', 'pre-tracking'),
  ('008_buddy_events.sql', 'e95f6d2ce77e0ad8f9cce5383f205dbc417bf596ce87618fb4b97554cea6f284', NULL, 'backfill', 'pre-tracking'),
  ('008_dream_mode.sql', 'fb21f16a6e08d4733af4b7639ff6c3794b1642a8df914d67786c750e6df6d2f3', NULL, 'backfill', 'pre-tracking'),
  ('008_fix_gateway_health_url.sql', '7f188b71556bf93d67c4a766e5f8d0be9016169328fd67f6c08b87e52e5f3340', NULL, 'backfill', 'pre-tracking'),
  ('008b_task_events.sql', 'ea88242d48b1817a70d7bf6c0e419872b2a058038c50df486bfe43437dc6fc9a', NULL, 'backfill', 'pre-tracking'),
  ('009_child_profiles.sql', '97a0cf5d64f74fa697bef9f19c9f4d1e2d7ca361c7d7035dfd44d9e675efb9b7', NULL, 'backfill', 'pre-tracking'),
  ('009_cost_center.sql', '4ee6b16d0f3fec5f5e3ee42cf91b16c81752a67e2fd576143d0e2203cb31f7d1', NULL, 'backfill', 'pre-tracking'),
  ('010_approval_gateway.sql', 'fc91d1c1acbe667919b88f568ed54facb416bb7468d0b4ff3362b42ad3c40cd4', NULL, 'backfill', 'pre-tracking'),
  ('010_cost_tracking.sql', '823efba7bd6b6548113a6e87e829581b19409e89cccf08a558c307b02a7c1c84', NULL, 'backfill', 'pre-tracking'),
  ('011_buddy_events_columns.sql', 'dab5ab5fb12866a0f33a334b5498246ed439b4298cc4632e2920caab62813823', NULL, 'backfill', 'pre-tracking'),
  ('011_power_tracking.sql', 'd8584ebe385d26e13d7fd6572f5acc9d8dc67e09b2b5898c835690d15efd68c6', NULL, 'backfill', 'pre-tracking'),
  ('012_alpha_briefings.sql', 'ad39e58a72c22c4c6bf5b41cc7456f223439713eff42f260c5d9aa8f4bb9c583', NULL, 'backfill', 'pre-tracking'),
  ('012_watchdog_events.sql', 'e5719f029ec8745009682d993628579e895e024db257fd53da7db8c535ac8639', NULL, 'backfill', 'pre-tracking'),
  ('013_workspace_seeding.sql', '7bc445d791b04593639b5d439a5ad7d35dc461821f7345c0a4d90ba679a68b45', NULL, 'backfill', 'pre-tracking'),
  ('014_vault_rls_v1.sql', '4e10d4acc2be3bb3cb1c5fdb0edf8c5aadb064c0d0a8e08ef85be088bb66f0c7', NULL, 'backfill', 'pre-tracking'),
  ('015_chat_rls_fix.sql', '80bb41d77e7e9c9621ac4fd057ab37f1fc66a8dfcc52ed1d78735be5ab53f2d9', NULL, 'backfill', 'pre-tracking')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
