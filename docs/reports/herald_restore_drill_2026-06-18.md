# Herald Restore Drill — 2026-06-18

| Field | Value |
|---|---|
| Status | PASS |
| Run timestamp | 20260618_235103 UTC |
| Source database | jarvis_alpha |
| Scratch database | jarvis_alpha_herald_drill_20260618_235103_47165 (dropped after verification) |
| Tables verified | 5 |
| Restored Herald tables found | 5 |
| Append-only send trigger found | 1 |
| Live rows | 50 |
| Restored rows | 50 |

## Table Counts

| Table | Live rows | Restored rows | Match |
|---|---:|---:|---|
| `public.alpha_at0_mail_scan_runs` | 28 | 28 | yes |
| `public.alpha_at0_mail_messages` | 1 | 1 | yes |
| `public.alpha_at0_mail_draft_proposals` | 1 | 1 | yes |
| `public.alpha_at0_mail_send_events` | 6 | 6 | yes |
| `public.alpha_at0_mail_graph_health` | 14 | 14 | yes |

## Evidence Notes

- Drill restored Herald mail intake, draft proposal, append-only send audit, and Graph health monitor tables into an isolated scratch database.
- Report intentionally records metadata and row counts only. It does not include email body previews, reply draft text, Graph tokens, or secrets.
- Scratch dump files were mode 600 and removed after the drill.
