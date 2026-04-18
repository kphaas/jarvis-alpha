# Session Close Manifest Schema

Single JSON file per session drives both `gh_sync.py` and `handoff_scaffold.py`. Lives in `manifests/YYYY-MM-DD.json`. Commit alongside session close.

## Structure

```json
{
  "session_date": "YYYY-MM-DD",
  "session_sequence": "01",
  "session_commit_range": {
    "from": "abc1234",
    "to": "def5678"
  },
  "labels_to_ensure": [
    {"name": "label-name", "color": "HEXCOLOR", "description": "..."}
  ],
  "close_existing": [
    {
      "issue_number": 42,
      "td_id": "TD-94",
      "comment": "Closing narrative with commit hash for hash-regex extraction..."
    }
  ],
  "create_and_close": [
    {
      "td_id": "TD-105",
      "title": "TD-105: Full title here",
      "body": "Markdown body content...",
      "labels": ["infra", "P2-medium"],
      "close_comment": "Closed same-session by commit <hash>..."
    }
  ],
  "create_open": [
    {
      "td_id": "TD-99",
      "title": "TD-99: Title",
      "body": "Markdown body content...",
      "labels": ["debt", "docs", "P2-medium"]
    }
  ],
  "handoff": {
    "tldr": "1-2 paragraph summary of the session",
    "architecture_decisions": [
      {"title": "Decision title", "description": "Full prose description"}
    ],
    "next_session_entry": "What the next session should open with",
    "lessons_learned": ["Short bullet strings"]
  }
}
```

## Field Reference

### Top level
- `session_date` (required) — `YYYY-MM-DD`, drives output filenames
- `session_sequence` (optional, default `"01"`) — handoff sequence number
- `session_commit_range` — `from`/`to` commit hashes for audit trail

### `labels_to_ensure`
- Ensures labels exist before issue operations. Idempotent via `--force`.
- `color`: hex without `#` prefix (e.g., `"0E8A16"`)

### `close_existing`
- Issues that ALREADY EXIST on GitHub and need closing.
- `issue_number` must match the real GitHub issue.
- `comment` should include closing commit hash for traceability.

### `create_and_close`
- Create an issue + immediately close it. Audit-trail pattern for architectural decisions that shipped same-session but warrant a dedicated issue.
- `close_comment` should reference the shipping commit.

### `create_open`
- New tech debt issues to track going forward.

### `handoff`
- Fields consumed by `handoff_scaffold.py` only.
- `architecture_decisions` and `lessons_learned` are optional; scaffold will insert placeholders if missing.

## Workflow

1. Copy `manifests/TEMPLATE.json` to `manifests/YYYY-MM-DD.json`
2. Fill in session data
3. Dry-run GitHub sync: `python3 gh_sync.py --manifest manifests/YYYY-MM-DD.json`
4. Execute: `python3 gh_sync.py --manifest manifests/YYYY-MM-DD.json --execute`
5. Generate handoff: `python3 handoff_scaffold.py --manifest manifests/YYYY-MM-DD.json`
6. Enhance the scaffold with narrative
7. Commit: manifest + tools + handoff (separate commits recommended)

## Resume After Failure

If `gh_sync.py --execute` halts mid-run, re-run with `--skip-existing` to avoid duplicates:

```
python3 gh_sync.py --manifest manifests/YYYY-MM-DD.json --execute --skip-existing
```

The tool matches on exact title string to detect already-created issues.

## See Also

- `gh_sync.py` — GitHub sync implementation
- `handoff_scaffold.py` — handoff template generator
- `manifests/TEMPLATE.json` — starting point for new sessions
