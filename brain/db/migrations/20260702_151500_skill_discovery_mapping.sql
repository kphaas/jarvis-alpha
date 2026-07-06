-- Migration: 20260702_151500_skill_discovery_mapping
-- Purpose: add metadata-only Codex/Claude skill-file, MCP tool, and AgentFS
--          references for the Agent Board skill discovery map.

UPDATE public.alpha_skill_registry
SET metadata = jsonb_set(
    metadata,
    '{discovery}',
    $json$
    {
      "mapping_source": "20260702_151500_skill_discovery_mapping",
      "codex_skill_refs": [
        {
          "name": "at0-gap-analysis",
          "ref": "codex://skills/at0-gap-analysis/SKILL.md",
          "status": "mapped",
          "description": "Evidence-based AT-0 capability gap analysis."
        },
        {
          "name": "status-dashboard",
          "ref": "codex://skills/status-dashboard/SKILL.md",
          "status": "mapped",
          "description": "One-page operator readiness/status dashboard."
        },
        {
          "name": "production",
          "ref": "codex://skills/production/SKILL.md",
          "status": "mapped",
          "description": "Production-readiness gate for PR, deploy, and rollback evidence."
        }
      ],
      "agentfs_refs": [
        {
          "name": "work_item_handoff",
          "ref": "agentfs://runs/{run_id}/outputs/work-item-handoff.json",
          "status": "available",
          "description": "Executor handoffs from Agent Board work items should be stored as governed AgentFS artifacts.",
          "metadata": {
            "artifact_table": "public.alpha_agent_run_artifacts",
            "stores_skill_file_bodies": false
          }
        }
      ]
    }
    $json$::jsonb,
    true
)
WHERE skill_name IN (
    'agent_board.read',
    'agent_board.queue_item',
    'agent_board.update_status',
    'agent_board.dispatch_item'
);

UPDATE public.alpha_skill_registry
SET metadata = jsonb_set(
    metadata,
    '{discovery}',
    $json$
    {
      "mapping_source": "20260702_151500_skill_discovery_mapping",
      "codex_skill_refs": [
        {
          "name": "status-dashboard",
          "ref": "codex://skills/status-dashboard/SKILL.md",
          "status": "mapped",
          "description": "Scheduled-work status and operator follow-up summary."
        },
        {
          "name": "production",
          "ref": "codex://skills/production/SKILL.md",
          "status": "mapped",
          "description": "Readiness gate before a schedule-driven workflow is enabled."
        }
      ],
      "claude_skill_refs": [
        {
          "name": "anthropic-skills:schedule",
          "ref": "claude://skills/anthropic-skills/schedule/SKILL.md",
          "status": "mapped",
          "description": "Natural-language schedule intent handling reference."
        }
      ],
      "agentfs_refs": [
        {
          "name": "scheduled_work_run",
          "ref": "agentfs://runs/{run_id}/outputs/scheduled-work-run.json",
          "status": "available",
          "description": "Materialized scheduled-work outputs should be stored as governed AgentFS artifacts.",
          "metadata": {
            "artifact_table": "public.alpha_agent_run_artifacts",
            "stores_skill_file_bodies": false
          }
        }
      ]
    }
    $json$::jsonb,
    true
)
WHERE skill_name IN (
    'agent_schedule.read',
    'agent_schedule.create',
    'agent_schedule.materialize_due'
);

UPDATE public.alpha_skill_registry
SET metadata = jsonb_set(
    metadata,
    '{discovery}',
    $json$
    {
      "mapping_source": "20260702_151500_skill_discovery_mapping",
      "codex_skill_refs": [
        {
          "name": "comp-scan",
          "ref": "codex://skills/comp-scan/SKILL.md",
          "status": "mapped",
          "description": "Compressed competitive/source scan workflow."
        },
        {
          "name": "at0-gap-analysis",
          "ref": "codex://skills/at0-gap-analysis/SKILL.md",
          "status": "mapped",
          "description": "AT-0 feature gap analysis and evidence review."
        }
      ],
      "mcp_tool_refs": [
        {
          "name": "beacon.crawler.scrape",
          "ref": "mcp://beacon-crawler/beacon.crawler.scrape",
          "status": "planned",
          "description": "Thin MCP adapter over Beacon crawler scrape.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/scrape",
            "risk_tier": "T2"
          }
        },
        {
          "name": "beacon.crawler.extract",
          "ref": "mcp://beacon-crawler/beacon.crawler.extract",
          "status": "planned",
          "description": "Thin MCP adapter over Beacon crawler extract.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/extract",
            "risk_tier": "T2"
          }
        }
      ],
      "agentfs_refs": [
        {
          "name": "research_evidence",
          "ref": "agentfs://runs/{run_id}/outputs/research-evidence.json",
          "status": "available",
          "description": "Search evidence snapshots should be stored as governed AgentFS artifacts.",
          "metadata": {
            "artifact_table": "public.alpha_agent_run_artifacts",
            "stores_skill_file_bodies": false
          }
        }
      ]
    }
    $json$::jsonb,
    true
)
WHERE skill_name = 'internet_scout.search';

UPDATE public.alpha_skill_registry
SET metadata = jsonb_set(
    metadata,
    '{discovery}',
    $json$
    {
      "mapping_source": "20260702_151500_skill_discovery_mapping",
      "codex_skill_refs": [
        {
          "name": "at0-gap-analysis",
          "ref": "codex://skills/at0-gap-analysis/SKILL.md",
          "status": "mapped",
          "description": "AT-0 gap analysis with cited evidence."
        },
        {
          "name": "five-lens-review",
          "ref": "codex://skills/five-lens-review/SKILL.md",
          "status": "mapped",
          "description": "Cross-lens review for architecture, ops, finance, and UX tradeoffs."
        },
        {
          "name": "comp-scan",
          "ref": "codex://skills/comp-scan/SKILL.md",
          "status": "mapped",
          "description": "Competitive/source scan workflow."
        }
      ],
      "claude_skill_refs": [
        {
          "name": "anthropic-skills:pdf",
          "ref": "claude://skills/anthropic-skills/pdf/SKILL.md",
          "status": "mapped",
          "description": "PDF evidence handling reference for research handoffs."
        },
        {
          "name": "anthropic-skills:docx",
          "ref": "claude://skills/anthropic-skills/docx/SKILL.md",
          "status": "mapped",
          "description": "Document evidence handling reference for research handoffs."
        }
      ],
      "mcp_tool_refs": [
        {
          "name": "beacon.crawler.batch_scrape",
          "ref": "mcp://beacon-crawler/beacon.crawler.batch_scrape",
          "status": "planned",
          "description": "Thin MCP adapter over Beacon batch scrape.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/batch-scrape",
            "risk_tier": "T2"
          }
        },
        {
          "name": "beacon.crawler.map",
          "ref": "mcp://beacon-crawler/beacon.crawler.map",
          "status": "planned",
          "description": "Thin MCP adapter over Beacon same-host map.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/map",
            "risk_tier": "T3"
          }
        },
        {
          "name": "beacon.crawler.crawl",
          "ref": "mcp://beacon-crawler/beacon.crawler.crawl",
          "status": "planned",
          "description": "Thin MCP adapter over Beacon crawl.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/crawl",
            "risk_tier": "T3"
          }
        }
      ],
      "agentfs_refs": [
        {
          "name": "research_handoff",
          "ref": "agentfs://runs/{run_id}/outputs/research-handoff.json",
          "status": "available",
          "description": "Deep research handoffs should be stored as governed AgentFS artifacts.",
          "metadata": {
            "artifact_table": "public.alpha_agent_run_artifacts",
            "stores_skill_file_bodies": false
          }
        }
      ]
    }
    $json$::jsonb,
    true
)
WHERE skill_name = 'internet_scout.deep_research';

UPDATE public.alpha_skill_registry
SET metadata = jsonb_set(
    metadata,
    '{discovery}',
    $json$
    {
      "mapping_source": "20260702_151500_skill_discovery_mapping",
      "codex_skill_refs": [
        {
          "name": "browser:control-in-app-browser",
          "ref": "codex://skills/browser/control-in-app-browser/SKILL.md",
          "status": "mapped",
          "description": "Browser-control workflow reference; Alpha execution remains approval-gated."
        },
        {
          "name": "production",
          "ref": "codex://skills/production/SKILL.md",
          "status": "mapped",
          "description": "Readiness gate for browser-runtime changes."
        }
      ],
      "mcp_tool_refs": [
        {
          "name": "beacon.crawler.render_approval_request",
          "ref": "mcp://beacon-crawler/beacon.crawler.render_approval_request",
          "status": "planned",
          "description": "Thin MCP adapter that queues a Beacon browser-render approval request.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/scrape/browser-approval-request",
            "risk_tier": "T4"
          }
        },
        {
          "name": "beacon.crawler.render_run_approved",
          "ref": "mcp://beacon-crawler/beacon.crawler.render_run_approved",
          "status": "planned",
          "description": "Thin MCP adapter that runs an already approved Beacon browser-render request.",
          "metadata": {
            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
            "route": "POST /v1/internet-scout/crawler/scrape/browser-run-approved",
            "risk_tier": "T4"
          }
        }
      ],
      "agentfs_refs": [
        {
          "name": "browser_evidence",
          "ref": "agentfs://runs/{run_id}/outputs/browser-evidence.json",
          "status": "available",
          "description": "Approved browser evidence should be stored as governed AgentFS artifacts.",
          "metadata": {
            "artifact_table": "public.alpha_agent_run_artifacts",
            "stores_skill_file_bodies": false
          }
        }
      ]
    }
    $json$::jsonb,
    true
)
WHERE skill_name = 'internet_scout.browser_task';

DO $$
DECLARE
    mapped_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO mapped_count
      FROM public.alpha_skill_registry
     WHERE metadata->'discovery'->>'mapping_source' = '20260702_151500_skill_discovery_mapping';

    IF mapped_count < 10 THEN
        RAISE EXCEPTION 'POST-FLIGHT skill discovery mapping FAILED: expected at least 10 mapped rows, found %', mapped_count;
    END IF;

    RAISE NOTICE 'POST-FLIGHT skill discovery mapping OK: % rows', mapped_count;
END $$;
