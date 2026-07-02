"""
Route classification registry for Approval Gateway.

Every API route is classified by action classes, which determine risk tier.
Unclassified routes default to T5 (deny by default).
"""

from collections.abc import Mapping
from typing import TypeVar


_T = TypeVar("_T")

# Action class → route mapping
# Lookup is method + longest prefix match
ROUTE_CLASSIFICATION: dict[str, list[str]] = {
    # Reads — T1
    "GET /health": ["read"],
    "GET /v1/mesh/status": ["read"],
    "GET /v1/home/summary": ["read"],
    "GET /v1/home/homie/state": ["read", "security_read"],
    "GET /v1/home/homie/events/stream": ["read", "security_read"],
    "POST /v1/home/homie/intent": ["write", "security_write"],
    "POST /v1/home/homie/voice-intent": ["write", "security_write"],
    "GET /v1/buddy/events": ["read"],
    "GET /v1/costs/summary": ["read"],
    "GET /v1/unifi/status": ["read"],
    "GET /v1/unifi/wan": ["read"],
    "GET /v1/unifi/clients": ["read"],
    "GET /v1/unifi/summary": ["read"],
    "GET /v1/unifi/health-check": ["read"],
    "GET /v1/tasks/graphs": ["read"],
    "GET /v1/approval": ["read"],
    "GET /v1/security/status": ["read", "security_read"],
    "GET /v1/security/audit": ["read", "security_read"],
    "GET /v1/mesh/certs": ["read"],
    "GET /v1/logs/query": ["read", "security_read"],
    "GET /v1/prompts/": ["read"],
    "GET /v1/prompts/{prompt_id}": ["read"],
    "POST /v1/approvals/unlock": ["approval_unlock"],
    "GET /v1/approvals/pending": ["read", "security_read"],
    "POST /v1/approvals/{id}/decide": ["approval_decide"],
    # Writes — T2
    "POST /v1/tasks/ingest": ["write"],
    "POST /v1/memory": ["write"],
    "PATCH /v1/tasks": ["write"],
    "POST /v1/prompts/": ["write"],
    "POST /v1/home/homie/action": ["write", "security_write"],
    "POST /v1/home/homie/approvals/{approval_id}/review": ["write", "security_write"],
    "POST /v1/home/homie/approvals/{approval_id}/resume": ["write", "security_write"],
    "POST /v1/home/homie/approvals/{approval_id}/execute": ["write", "security_write"],
    # Chat — varies by model routing (local=write, cloud=external_call+cost)
    # Default to write — cloud escalation handled at route level
    "POST /v1/chat": ["write"],
    "PUT /v1/chat": ["write"],
    "DELETE /v1/chat": ["write"],
    # Ask — always involves potential cloud call
    "POST /v1/ask": ["write", "external_call", "cost_incurring"],
    # Cloud calls — T3
    "POST /v1/cloud/call": ["external_call", "cost_incurring"],
    # Dream mode — controlled by scopes, but classify for audit
    # Auth — admin
    "GET /v1/auth/login-profiles": ["read"],
    "GET /v1/auth/profiles": ["read", "security_read"],
    "POST /v1/auth/set-child-pin": ["write", "security_write"],
    "POST /v1/auth/set-profile-pin": ["write", "security_write"],
    "POST /v1/auth/set-admin-pin": ["write", "security_write"],
    "GET /v1/auth/session": ["auth"],
    "POST /v1/auth/session-cookie": ["auth"],
    # Settings — PI/config reads are security reads; writes are admin-scoped.
    "GET /v1/settings/web-agent": ["read", "security_read"],
    "PUT /v1/settings/web-agent/home-location": ["write", "security_write"],
    "GET /v1/settings/identity": ["read", "security_read"],
    "POST /v1/settings/users": ["write", "security_write"],
    "PUT /v1/settings/users/{profile_id}/personal-data": [
        "write",
        "security_write",
    ],
    "PUT /v1/settings/relationships": ["write", "security_write"],
    "DELETE /v1/settings/relationships/{relationship_id}": ["destructive"],
    "PUT /v1/settings/personal-data/home-address": ["write", "security_write"],
    # Admin
    "POST /v1/admin": ["admin"],
    # Destructive
    "DELETE /v1/memory": ["destructive"],
    # Approval routes themselves — read/write
    "POST /v1/approval/request": ["write"],
    "GET /v1/approval/{id}/status": ["read"],
    "POST /v1/approval/{id}/decide": ["admin"],
    # Honeypot
    "POST /v1/honeypot": ["write"],
    "GET /v1/honeypot": ["read"],
    # --- Metrics (system internal) — T1 read ---
    "POST /v1/metrics/power": ["write"],
    "GET /v1/metrics/power/current": ["read"],
    "GET /v1/metrics/power/history": ["read"],
    "GET /v1/metrics/power/rate": ["read"],
    "GET /v1/metrics/power/rollup": ["read"],
    "POST /v1/metrics/power/rollup": [
        "write"
    ],  # Scheduled hourly rollup — writes to alpha_power_hourly/daily
    # --- Security panel — T2 security_read ---
    "GET /v1/security/jwt-check": ["read", "security_read"],
    "GET /v1/security/rls-status": ["read", "security_read"],
    "GET /v1/security/secrets-audit": ["read", "security_read"],
    "GET /v1/security/perimeter": ["read", "security_read"],
    "GET /v1/security/porchlight": ["read", "security_read"],
    "GET /v1/security/keyturner-status": ["read", "security_read"],
    "GET /v1/security/warden-status": ["read", "security_read"],
    "GET /v1/security/agent-events": ["read", "security_read"],
    "POST /v1/security/sentinel-report": ["write", "security_write"],
    "POST /v1/security/sweep-report": ["write", "security_write"],
    "GET /v1/security/rotatable-keys": ["read", "security_read"],
    # Keyturner owns its own T4 approval bridge inside the route. The outer
    # route must pass through so SkillRunner can queue/consume the exact
    # secrets.rotate request without storing the new secret value.
    "POST /v1/security/rotate-key": ["write", "security_write", "keyturner_rotate"],
    # --- Logs — T2 security_read ---
    "GET /v1/logs/analyze-patterns": ["read", "security_read"],
    "GET /v1/logs/diagnose": ["read", "security_read"],
    # --- Tasks — reads T1, writes T2, step approve/deny T4 ---
    "GET /v1/tasks/events": ["read"],
    "GET /v1/tasks/graphs/{graph_id}": ["read"],
    "GET /v1/tasks/graphs/{graph_id}/status": ["read"],
    "GET /v1/tasks/graphs/{graph_id}/steps": ["read"],
    "GET /v1/tasks/pending-approvals": ["read"],
    "POST /v1/tasks/submit": ["write"],
    "POST /v1/tasks/{graph_id}/cancel": ["write"],
    "POST /v1/tasks/steps/{step_id}/approve": ["admin"],
    "POST /v1/tasks/steps/{step_id}/deny": ["admin"],
    # --- Threads — reads T1, writes T2. Thread delete is a self-owned soft
    # archive guarded in-route for child profiles, so it stays T2 instead of
    # approval-gated T5.
    "GET /v1/threads": ["read"],
    "GET /v1/sessions/search": ["read", "security_read"],
    "GET /v1/threads/{thread_id}": ["read"],
    "GET /v1/threads/{thread_id}/messages": ["read"],
    "POST /v1/threads": ["write"],
    "POST /v1/threads/{thread_id}/messages": ["write"],
    "POST /v1/threads/{thread_id}/escalate": ["write"],
    "DELETE /v1/threads/{thread_id}": ["write"],
    # --- Memory reads — T1 ---
    "GET /v1/memory": ["read"],
    "GET /v1/memory/search": ["read"],
    "GET /v1/memory/graph": ["read"],
    "GET /v1/memory/graph/history/{object_id}": ["read"],
    "GET /v1/memory/admin/users/{principal_id}/graph": ["read", "security_read"],
    "GET /v1/memory/admin/graph/health": ["read", "security_read"],
    "GET /v1/memory/admin/graph/proposals": ["read", "security_read"],
    "GET /v1/memory/admin/dream-proposals": ["read"],
    "POST /v1/memory/graph/proposals": ["write"],
    "POST /v1/memory/graph/proposals/{proposal_id}/execute": ["write"],
    "POST /v1/memory/buddy-events/read": ["write"],
    "POST /v1/memory/buddy-events/suppress-duplicates": ["write"],
    "POST /v1/memory/admin/buddy-events/read": ["write"],
    "POST /v1/memory/admin/buddy-events/suppress-duplicates": ["write"],
    "PATCH /v1/memory/semantic/{memory_id}": ["write"],
    # --- ADR-0026 reviewed memory consolidation bridge ---
    # Proposal creation and execution own their proposal-specific T5 approval
    # queue/validation in-route. The outer middleware must pass them through so
    # the route can create or consume the exact reviewed-write approval item.
    "POST /v1/memory/consolidation/proposals": ["write"],
    "POST /v1/memory/consolidation/proposals/{proposal_id}/execute": ["write"],
    "POST /v1/memory/consolidation/proposals/{proposal_id}/archive": ["write"],
    "POST /v1/memory/consolidation/proposals/{proposal_id}/revert": [
        "memory_consolidation_reviewed_write"
    ],
    "POST /v1/memory/consolidation/{unknown_action}": ["unclassified"],
    # --- Rotation — T2 security_read ---
    "GET /v1/rotation": ["read", "security_read"],
    # --- Dev — T5 admin ---
    "POST /v1/dev/analyze": [
        "write",
        "external_call",
    ],  # Code analysis via local Ollama + GitHub API — no DB write, no cloud cost
    "POST /v1/dev": ["admin"],
    # --- Review — T2 pass-through (Forge service review calls, local Ollama, $0) ---
    "POST /v1/review": ["write", "external_call"],  # TASK-001 Deliverable A
    # --- Internal LLM tool-call — T2 pass-through (service-only, local Ollama,
    # $0, no memory/embedding side effects). Not cost_incurring (local = free). ---
    "POST /v1/internal/complete": ["external_call"],
    # --- Diagnose — T2 security_read ---
    "GET /v1/diagnose": ["read", "security_read"],
    # --- Health agents — T1 read ---
    "GET /v1/health/agents": ["read"],
    "GET /v1/health/temporal-storage": ["read", "security_read"],
    "GET /v1/health/maintainer": ["read", "security_read"],
    # --- Helm read-only workspace summary ---
    "GET /v1/helm/summary": ["read", "security_read"],
    "GET /v1/helm/ai-news/brief": ["read", "security_read"],
    "GET /v1/helm/markets/brief": ["read", "security_read"],
    "GET /v1/helm/self": ["read", "security_read"],
    "GET /v1/helm/family/summary": ["read", "security_read"],
    "GET /v1/helm/financial/summary": ["read", "security_read"],
    "GET /v1/helm/medical/summary": ["read", "security_read"],
    "GET /v1/helm/actions/status": ["read", "security_read"],
    "POST /v1/helm/actions/propose": ["write", "security_write"],
    "POST /v1/helm/voice/transcribe": ["write", "security_write"],
    "POST /v1/helm/voice/speak": ["write", "security_write"],
    # --- Beacon internet evidence broker ---
    "GET /v1/internet-scout/health": ["read", "security_read"],
    "GET /v1/internet-scout/retention/report": ["read", "security_read"],
    "POST /v1/internet-scout/retention/delete-expired": [
        "write",
        "security_write",
        "destructive",
    ],
    "POST /v1/internet-scout/research": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/internet-scout/agent/run": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/internet-scout/local-llm/tool": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/internet-scout/local-llm/tool/stream": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/internet-scout/consumers/{consumer}/local-llm/tool": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/internet-scout/crawler/scrape": ["write", "external_call"],
    "POST /v1/internet-scout/crawler/batch-scrape": ["write", "external_call"],
    "POST /v1/internet-scout/crawler/scrape/browser-approval-request": [
        "write",
        "security_write",
    ],
    "POST /v1/internet-scout/crawler/scrape/browser-run-approved": [
        "write",
        "security_write",
        "external_call",
    ],
    "POST /v1/internet-scout/crawler/map": ["write", "external_call"],
    "POST /v1/internet-scout/crawler/crawl": ["write", "external_call"],
    "POST /v1/internet-scout/crawler/extract": ["write", "external_call"],
    "POST /v1/internet-scout/browser-task/approval-request": [
        "write",
        "security_write",
    ],
    "GET /v1/internet-scout/browser-task/history": ["read", "security_read"],
    "POST /v1/internet-scout/requests/{request_id}/memory-promotions": [
        "write",
        "security_write",
    ],
    "POST /v1/internet-scout/memory-promotions/{promotion_id}/review": [
        "write",
        "security_write",
    ],
    # P8 browser runner verifies and consumes the exact approved Beacon queue
    # row in-route; outer middleware stays pass-through like other bridges.
    "POST /v1/internet-scout/browser-task/run-approved": [
        "write",
        "security_write",
        "external_call",
    ],
    "GET /v1/internet-scout/requests": ["read", "security_read"],
    "GET /v1/internet-scout/requests/{request_id}": ["read", "security_read"],
    # --- Honeypot events — T1 read ---
    "GET /v1/honeypot/events": ["read"],
    # --- Honeypot traps — T1 read (they just log) ---
    "GET /wp-login.php": ["read"],
    "POST /wp-login.php": ["read"],
    "GET /.env": ["read"],
    "GET /.git/config": ["read"],
    "GET /phpmyadmin": ["read"],
    "GET /phpmyadmin/": ["read"],
    "GET /api/v1/debug": ["read"],
    # --- Vault — T2 write ---
    "POST /v1/vault/upload": ["write"],
    "POST /v1/vault/ingest/pdf": ["write"],
    "POST /v1/vault/ingest/docx": ["write"],
    "POST /v1/vault/ingest/text": ["write"],
    "POST /v1/vault/ingest/excel": ["write"],
    "POST /v1/vault/digests/private": ["write"],
    # --- Chat completions (OpenAI compat) ---
    "POST /v1/chat/completions": ["write", "external_call", "cost_incurring"],
    # --- Buddy events mark read — T2 write ---
    "POST /v1/buddy/events/{event_id}/read": ["write"],
    "POST /v1/buddy/events/read-all": ["write"],
    # --- Briefings — JWT scopes in route handlers: forge.briefings.ingest (POST ingest),
    #     briefings.read or admin on GETs. T2 write / T1 read; service-to-service ingest.
    "POST /v1/briefings/ingest": ["write"],
    "GET /v1/briefings": ["read"],
    "GET /v1/briefings/latest": ["read"],
    "GET /v1/briefings/{batch_run_id}": ["read"],
    # --- School email intelligence — Gmail read-only scan + reviewed candidates ---
    "GET /v1/school-email/candidates": ["read", "security_read"],
    "GET /v1/school-email/actions": ["read", "security_read"],
    "GET /v1/school-email/scan-runs/latest": ["read", "security_read"],
    "GET /v1/school-email/gmail/health": ["read", "security_read"],
    "POST /v1/school-email/scan": ["write", "external_call"],
    "POST /v1/school-email/gmail/health/check": ["write", "external_call"],
    "POST /v1/school-email/candidates/{candidate_id}/status": ["write"],
    "POST /v1/school-email/actions/{candidate_id}/status": ["write"],
    # --- AT-0 Herald mail — Graph ingestion, local drafts, approved replies ---
    "GET /v1/at0-mail/dashboard": ["read", "security_read"],
    "GET /v1/at0-mail/health": ["read", "security_read"],
    "GET /v1/at0-mail/mailboxes": ["read", "security_read"],
    "GET /v1/at0-mail/spark-profile": ["read", "security_read"],
    "GET /v1/at0-mail/messages": ["read", "security_read"],
    "GET /v1/at0-mail/drafts": ["read", "security_read"],
    "POST /v1/at0-mail/scan": ["write", "external_call"],
    "POST /v1/at0-mail/drafts/{draft_id}/status": ["write", "security_write"],
    "POST /v1/at0-mail/drafts/{draft_id}/send": [
        "write",
        "security_write",
        "external_call",
        "email_send",
    ],
    # --- Herald social — draft-only local outbox, no platform publish connector ---
    "GET /v1/herald/social/platforms": ["read", "security_read"],
    "GET /v1/herald/social/drafts": ["read", "security_read"],
    "GET /v1/herald/social/linkedin/cadence": ["read", "security_read"],
    "GET /v1/herald/social/linkedin/read-plan": ["read", "security_read"],
    "GET /v1/herald/social/linkedin/operator-dashboard": ["read", "security_read"],
    "GET /v1/herald/social/linkedin/engagements": ["read", "security_read"],
    "GET /v1/herald/social/linkedin/thought-leaders": ["read", "security_read"],
    "POST /v1/herald/social/drafts": ["write", "security_write"],
    "POST /v1/herald/social/linkedin/weekly": ["write", "security_write"],
    "POST /v1/herald/social/linkedin/engagements": ["write", "security_write"],
    "POST /v1/herald/social/linkedin/metrics": ["write", "security_write"],
    "POST /v1/herald/social/linkedin/thought-leaders": ["write", "security_write"],
    "POST /v1/herald/social/linkedin/engagements/scout": [
        "write",
        "security_write",
        "external_call",
    ],
    "POST /v1/herald/social/linkedin/ingest": [
        "write",
        "security_write",
        "external_call",
    ],
    "POST /v1/herald/social/linkedin/engagements/{item_id}/draft-reply": [
        "write",
        "security_write",
    ],
    "POST /v1/herald/social/linkedin/engagements/{item_id}/publish-reply": [
        "write",
        "security_write",
        "external_call",
        "social_post",
    ],
    "POST /v1/herald/social/linkedin/engagements/{item_id}/status": [
        "write",
        "security_write",
    ],
    "POST /v1/herald/social/drafts/{variant_id}/status": [
        "write",
        "security_write",
    ],
    "POST /v1/herald/social/drafts/{variant_id}/schedule": [
        "write",
        "security_write",
    ],
    "POST /v1/herald/social/drafts/{variant_id}/publish/manual": [
        "write",
        "security_write",
    ],
    "POST /v1/herald/social/drafts/{variant_id}/publish/linkedin": [
        "write",
        "security_write",
        "external_call",
        "social_post",
    ],
    # --- Spark iMessage — metadata-only BlueBubbles read surface ---
    "GET /v1/spark/imessage/health": ["read", "security_read"],
    "GET /v1/spark/imessage/counts": ["read", "security_read"],
    "GET /v1/spark/imessage/recent-chats/metadata": ["read", "security_read"],
    "GET /v1/spark/imessage/readiness": ["read", "security_read"],
    # --- Spark persona — editable guardrails, no corpus content ---
    "GET /v1/spark/persona/auto-context": ["read", "security_read"],
    "GET /v1/spark/persona/guardrails": ["read", "security_read"],
    "GET /v1/spark/persona/memory": ["read", "security_read"],
    "GET /v1/spark/persona/target-memory": ["read", "security_read"],
    "PUT /v1/spark/persona/guardrails": ["write", "security_write"],
    "POST /v1/spark/persona/memory/propose": ["write", "security_write"],
    "POST /v1/spark/persona/memory/route": ["write", "security_write"],
    "POST /v1/spark/persona/memory/approve": ["write", "security_write"],
    "POST /v1/spark/persona/memory/archive": ["write", "security_write"],
    "POST /v1/spark/persona/memory/reject": ["write", "security_write"],
    "POST /v1/spark/persona/target-memory/propose": ["write", "security_write"],
    "POST /v1/spark/persona/target-memory/approve": ["write", "security_write"],
    "POST /v1/spark/persona/target-memory/archive": ["write", "security_write"],
    "POST /v1/spark/persona/target-memory/reject": ["write", "security_write"],
    # --- Spark drafts — local draft proposal, no external send ---
    "GET /v1/spark/drafts/imessage/targets": ["read", "security_read"],
    "GET /v1/spark/drafts/imessage/target-preview": ["read", "security_read"],
    "GET /v1/spark/drafts/imessage/outbox": ["read", "security_read"],
    "POST /v1/spark/drafts/imessage": ["write", "security_write"],
    "POST /v1/spark/drafts/imessage/approval-request": [
        "write",
        "security_write",
    ],
    "POST /v1/spark/drafts/imessage/outbox/{outbox_id}/send": [
        "write",
        "security_write",
        "external_call",
        "imessage_send",
    ],
    "POST /v1/spark/drafts/imessage/outbox/{outbox_id}/trusted-live-send": [
        "write",
        "security_write",
        "external_call",
        "imessage_send",
    ],
    "POST /v1/spark/drafts/imessage/outbox/{outbox_id}/cancel": [
        "write",
        "security_write",
    ],
    "POST /v1/spark/drafts/imessage/feedback": ["write", "security_write"],
    # --- MCP registry — T1 read, write T2 ---
    "GET /v1/mcp/registry": ["read"],
    "POST /v1/mcp/registry": ["write"],
    # --- Dream sessions ---
    "GET /v1/dream/sessions": ["read"],
    "GET /v1/dream/health": ["read", "security_read"],
    "POST /v1/dream/sessions": ["write"],
    "POST /v1/dream/plan": ["write", "external_call", "cost_incurring"],
    "POST /v1/dream/review": ["write", "external_call", "cost_incurring"],
    "GET /v1/dream/sessions/{session_id}": ["read"],
    "GET /v1/dream/sessions/{session_id}/briefing": ["read"],
    "POST /v1/dream/sessions/{session_id}/start": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "GET /v1/dream/sessions/{session_id}/next-step": [
        "write",
        "external_call",
        "cost_incurring",
    ],
    "POST /v1/dream/sessions/{session_id}/complete": ["write"],
    "POST /v1/dream/sessions/{session_id}/kill": ["write"],
    "POST /v1/dream/sessions/{session_id}/execute-readonly": ["write"],
    "POST /v1/dream/sessions/{session_id}/execute-gated": ["write"],
    "POST /v1/dream/sessions/{session_id}/execute-approved": ["write"],
    "POST /v1/dream/sessions/{session_id}/briefing/publish": ["write"],
    "PATCH /v1/dream/steps/{step_id}": ["write", "cost_incurring"],
    # --- FastAPI built-in docs — T1 read ---
    "GET /docs": ["read"],
    "HEAD /docs": ["read"],
    "GET /docs/oauth2-redirect": ["read"],
    "HEAD /docs/oauth2-redirect": ["read"],
    "GET /openapi.json": ["read"],
    "HEAD /openapi.json": ["read"],
    "GET /redoc": ["read"],
    "HEAD /redoc": ["read"],
    # --- Costs — reads T1, writes T2, admin T5 ---
    "GET /v1/costs/budget": ["read"],
    "GET /v1/costs/credit": ["read"],
    "GET /v1/costs/hardware": ["read"],
    "GET /v1/costs/outcomes": ["read"],
    "GET /v1/costs/perplexity": ["read"],
    "GET /v1/costs/power": ["read"],
    "GET /v1/costs/subscriptions": ["read"],
    "POST /v1/costs/budget/{provider}": ["write", "cost_incurring"],
    "POST /v1/costs/credit": ["admin"],
    "POST /v1/costs/perplexity": ["write", "external_call", "cost_incurring"],
    "POST /v1/costs/power/rate": ["write"],
    "POST /v1/costs/subscriptions": ["write"],
    "DELETE /v1/costs/subscriptions/{sub_id}": ["destructive"],
    # --- Security child profiles — T2 security_read ---
    "GET /v1/security/child-profiles": ["read", "security_read"],
    "GET /v1/security/mcp/registry": ["read"],
    "GET /v1/security/mcp/adapters/beacon-crawler": ["read", "security_read"],
    # --- Vault — reads T1, writes T2 ---
    "GET /v1/vault/pipeline": ["read"],
    "POST /v1/vault/ask": ["read", "external_call", "cost_incurring"],
    "POST /v1/vault/search": ["read"],
    "POST /v1/vault/pipeline/{pipeline_id}/confirm": ["write"],
    # --- Logs — POST diagnose is T2 ---
    "POST /v1/logs/diagnose": ["write", "security_read"],
    # --- Tasks — additional routes ---
    "POST /v1/tasks/graphs": ["write"],
    "POST /v1/tasks/graphs/{graph_id}/approve": ["admin"],
    "POST /v1/tasks/graphs/{graph_id}/steps": ["write"],
    # --- Threads patch ---
    "PATCH /v1/threads/{thread_id}": ["write"],
    # --- Watchdog — T1 read (monitoring events) ---
    "GET /v1/watchdog/events": ["read"],
    "GET /v1/watchdog/status": ["read"],
    "POST /v1/watchdog/event": [
        "write"
    ],  # Node watchdog event ingestion — service-to-service telemetry
    "POST /v1/internal/cost-event": ["write"],
    # --- Skill and agent registries — reads T2, agent control T5 ---
    "GET /v1/skills": ["read", "security_read"],
    "GET /v1/skills/{skill_name}": ["read", "security_read"],
    "GET /v1/agents": ["read", "security_read"],
    "GET /v1/agents/status": ["read", "security_read"],
    "GET /v1/agents/{agent_id}": ["read", "security_read"],
    "GET /v1/agents/{agent_id}/events": ["read", "security_read"],
    "GET /v1/agents/{agent_id}/runs": ["read", "security_read"],
    "POST /v1/agents/{agent_id}/enable": ["admin"],
    "POST /v1/agents/{agent_id}/disable": ["admin"],
    # Manual run is still guarded in-route by agent allowlist, active/enabled
    # status, T1/T2 risk tier, and explicit metadata.manual_run_enabled.
    "POST /v1/agents/{agent_id}/run": ["write", "security_write"],
    "POST /v1/agent-runs/{run_id}/workspace/init": ["write", "security_write"],
    "GET /v1/agent-runs/{run_id}/workspace": ["read", "security_read"],
    "GET /v1/agent-runs/{run_id}/artifacts": ["read", "security_read"],
    "GET /v1/agent-runs/{run_id}/artifacts/{artifact_id}/preview": [
        "read",
        "security_read",
    ],
    "GET /v1/agent-runs/{run_id}/artifacts/{artifact_id}/download": [
        "read",
        "security_read",
    ],
    "GET /v1/agent-runs/{run_id}/artifacts/{artifact_id}/content": [
        "read",
        "security_read",
    ],
    "POST /v1/agent-runs/{run_id}/artifacts": ["write", "security_write"],
    # --- Alpha Agent Board — governed queue metadata and TaskGraph bridge ---
    "GET /v1/agent-board": ["read", "security_read"],
    "GET /v1/agent-board/registry": ["read", "security_read"],
    "GET /v1/agent-board/skill-map": ["read", "security_read"],
    "GET /v1/agent-board/work-items/{work_item_id}": ["read", "security_read"],
    "POST /v1/agent-board/work-items": ["write", "security_write"],
    "POST /v1/agent-board/work-items/{work_item_id}/task-graph": [
        "write",
        "security_write",
    ],
    "PATCH /v1/agent-board/work-items/{work_item_id}/status": [
        "write",
        "security_write",
    ],
    # --- Agent schedules — materializes queued board work, never executes it ---
    "GET /v1/agent-schedules": ["read", "security_read"],
    "POST /v1/agent-schedules": ["write", "security_write"],
    "PATCH /v1/agent-schedules/{schedule_id}/status": [
        "write",
        "security_write",
    ],
    "POST /v1/agent-schedules/materialize-due": ["write", "security_write"],
    # --- Privacy scrub intake — encrypted local-only writes, no outbound action ---
    "POST /v1/privacy/subjects": ["write", "security_write"],
    "POST /v1/privacy/subjects/{subject_id}/identity-tuples": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/subjects/{subject_id}/case-drafts": [
        "write",
        "security_write",
    ],
    "GET /v1/privacy/case-drafts": ["read", "security_read"],
    "GET /v1/privacy/actions/approved": ["read", "security_read"],
    "POST /v1/privacy/actions/{action_id}/manual-disposition": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/actions/{action_id}/verification": [
        "write",
        "security_write",
    ],
    "GET /v1/privacy/case-drafts/{case_id}/timeline": [
        "read",
        "security_read",
    ],
    "GET /v1/privacy/case-drafts/{case_id}/report": ["read", "security_read"],
    "GET /v1/privacy/case-drafts/{case_id}": ["read", "security_read"],
    "POST /v1/privacy/case-drafts/{case_id}/submit-approval": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/case-drafts/{case_id}/archive": [
        "write",
        "security_write",
    ],
    "GET /v1/privacy/removal-control/summary": ["read", "security_read"],
    "POST /v1/privacy/subjects/{subject_id}/removal-control/seed": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/subjects/{subject_id}/authorizations": [
        "write",
        "security_write",
    ],
    "GET /v1/privacy/subjects/{subject_id}/authorizations": [
        "read",
        "security_read",
    ],
    "POST /v1/privacy/actions/{action_id}/removal-request": [
        "write",
        "security_write",
    ],
    "GET /v1/privacy/removal-requests": ["read", "security_read"],
    "POST /v1/privacy/removal-requests/{request_id}/transition": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/removal-requests/{request_id}/dry-run": [
        "write",
        "security_write",
    ],
    "POST /v1/privacy/removal-requests/{request_id}/live-preflight": [
        "write",
        "security_write",
        "external_call",
    ],
    "GET /v1/privacy/targets": ["read", "security_read"],
    "POST /v1/privacy/targets/refresh": ["write", "security_write"],
    # --- ChatOps command ingress — read-only, token-authenticated by route ---
    "POST /v1/chatops/mattermost/command": ["read", "security_read"],
    # --- Financial approval bridge — route-local RS256 service auth ---
    "GET /v1/bridge/health": ["read", "security_read"],
    "POST /v1/bridge/approvals/submit": ["write"],
    "GET /v1/bridge/approvals/{approval_id}": ["read", "security_read"],
    # --- Admin panel ---
    "GET /admin": ["admin"],
    "POST /admin": ["admin"],
    "POST /v1/auth/pin": ["auth"],
}


# Tier assignment rules (order matters — first match wins)
# Each rule: (required_classes, tier)
# If action has ALL required_classes, that tier applies
TIER_RULES: list[tuple[set[str], str]] = [
    # Compound high-risk first
    ({"approval_decide"}, "T2"),
    ({"approval_unlock"}, "T2"),
    ({"memory_consolidation_reviewed_write"}, "T5"),
    ({"imessage_send"}, "T4"),
    ({"security_write"}, "T2"),
    ({"deploy", "child_facing"}, "T5"),
    ({"unclassified"}, "T5"),
    ({"destructive"}, "T5"),
    ({"admin"}, "T5"),
    ({"deploy"}, "T4"),
    ({"child_facing"}, "T4"),
    ({"cost_incurring"}, "T3"),
    ({"external_call"}, "T2"),
    ({"write"}, "T2"),
    ({"security_read"}, "T2"),
    ({"auth"}, "T2"),
    ({"read"}, "T1"),
]


def lookup_route_registry(
    method: str, path: str, registry: Mapping[str, _T]
) -> _T | None:
    """Resolve a method/path pair against a route registry."""
    method = method.upper()

    # Exact match first
    key = f"{method} {path}"
    if key in registry:
        return registry[key]

    # Longest prefix match — strip path segments from the right
    # e.g., "GET /v1/approval/abc-123/status" matches "GET /v1/approval/{id}/status"
    # But we can't match {id} literally — so match by prefix up to the parameterized segment
    best_match: str | None = None
    best_length = 0
    for registered_key in registry:
        reg_method, reg_path = registered_key.split(" ", 1)
        if reg_method != method:
            continue
        # Check if the registered path is a prefix of the request path
        # Handle parameterized paths: /v1/approval/{id}/status
        # Strip {param} segments and compare prefixes
        reg_segments = reg_path.strip("/").split("/")
        req_segments = path.strip("/").split("/")

        if len(reg_segments) > len(req_segments):
            continue

        match = True
        for i, seg in enumerate(reg_segments):
            if seg.startswith("{") and seg.endswith("}"):
                continue  # wildcard segment — matches anything
            if seg != req_segments[i]:
                match = False
                break

        if match and len(reg_segments) > best_length:
            best_length = len(reg_segments)
            best_match = registered_key

    if best_match:
        return registry[best_match]

    return None


def classify_route(method: str, path: str) -> list[str]:
    """Classify a route by method + longest prefix match.

    Returns action classes list. Unregistered routes return ["unclassified"].
    """
    classes = lookup_route_registry(method, path, ROUTE_CLASSIFICATION)
    if classes is not None:
        return classes

    return ["unclassified"]


def determine_risk_tier(action_classes: list[str], overnight: bool = False) -> str:
    """Determine risk tier from action classes.

    Applies tier rules in priority order — first match wins.
    Overnight mode escalates T3 → budget-checked (handled by middleware, not here).
    T4/T5 overnight → always queued (handled by middleware).
    """
    class_set = set(action_classes)

    for required, tier in TIER_RULES:
        if required.issubset(class_set):
            return tier

    # Fallback — should never reach here if TIER_RULES covers all classes
    return "T5"
