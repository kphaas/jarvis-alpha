# TD-40: Redesign promote_episodic_to_semantic

**Status:** DEFERRED — ripped from Stage 3 due to schema mismatch
**Created:** 2026-04-08 (Step 6.5 Stage 3 final fix)
**Priority:** P3 — memory not in production yet

## What Happened

Stage 3 originally shipped a `promote_episodic_to_semantic(p_user_id)` SECURITY DEFINER function that assumed `alpha_semantic_memory` had `content`, `embedding`, and `source_memory_id` columns. Smoke test caught the mismatch.

**Real `alpha_semantic_memory` schema:**
- `id UUID`
- `user_id UUID` (not TEXT)
- `fact TEXT` (distilled fact, not raw conversation content)
- `category TEXT` — CHECK: preference | person | project | constraint | health | child_profile
- `source TEXT` — CHECK: promoted | explicit | buddy
- `created_at`, `updated_at`
- `UNIQUE (user_id, fact)` — deduplication enforced

**Real `alpha_conversation_memory.content`** is raw conversation text. You cannot SQL-copy content → fact. You need an LLM extraction step that:
1. Reads conversation content
2. Distills it into a fact (e.g., "i prefer dark mode" → `fact='prefers dark mode', category='preference'`)
3. Categorizes the fact against the CHECK constraint
4. Deduplicates against existing facts for the user

This is not SQL — it's a pipeline.

## Decision Taken in Stage 3

- Dropped `promote_episodic_to_semantic(TEXT)` entirely
- Shrunk `run_buddy_memory_maintenance` omnibus from 5 ops to 4 (removed promote step)
- Memory maintenance still runs: evict working, evict episodic 30d, cap episodic at 1000, cap semantic at 200
- Semantic promotion is currently not happening anywhere in the system

## What Needs To Happen Before Memory Goes Production

1. **Design an LLM extraction pipeline** that runs periodically (per-user, probably Buddy) and:
   - Reads episodic conversations with `access_count >= N` (threshold TBD)
   - Calls an LLM with a system prompt like "extract any durable facts from this conversation"
   - Gets back structured output matching the semantic memory CHECK constraint categories
   - Writes to `alpha_semantic_memory` via SECURITY DEFINER function
   - Handles the UNIQUE (user_id, fact) dedup via ON CONFLICT
2. **Decide the trigger:** on every Buddy cycle, nightly, on-demand from user?
3. **Decide the cost ceiling:** LLM calls cost money — how many facts per user per day?
4. **Decide local vs cloud:** local Ollama extraction (free, slower, less reliable) or Claude Haiku (fast, cheap, accurate)?
5. **Write new SECURITY DEFINER function** matching the real schema: `record_semantic_fact(p_user_id UUID, p_fact TEXT, p_category TEXT, p_source TEXT) RETURNS UUID`

## Why Not Fix It In Stage 3

Stage 3 is foundation hardening — wrapping background writers in SECURITY DEFINER so Stage 5 can enable FORCE RLS safely. Designing a new LLM extraction pipeline is scope creep with production-impact unknowns.

The table has near-zero rows today. Zero users depend on semantic promotion right now. Deferring costs nothing.

## Acceptance Criteria (For Future TD-40 Closure)

- [ ] LLM extraction function designed and documented
- [ ] New SECURITY DEFINER function matching real schema
- [ ] Added back to run_buddy_memory_maintenance omnibus
- [ ] Smoke test covers end-to-end extraction + insert
- [ ] Cost/rate limits documented and enforced
- [ ] Buddy cycle includes promotion step

## Cross-References

- `docs/STAGE3_DISCOVERY.md` — where the schema mismatch was first missed
- `brain/db/migrations/20260408_150000_evict_fix_and_promote_rip.sql` — where promote was ripped
- `brain/db/migrations/20260408_130000_security_definer_functions.sql` — original (wrong) implementation
