"""Beacon internet-scout service contracts.

Beacon is Alpha's internet evidence broker. Brain owns policy, planning, and
stored evidence; Gateway owns guarded public egress and extraction.
"""

from brain.services.internet_scout.models import (
    BeaconConsumer,
    BrowserRunObservation,
    BrowserSandboxPolicy,
    EvidenceClaim,
    GatewayCrawlResponse,
    InternetScoutBrowserRunRequest,
    InternetScoutBrowserRunResponse,
    InternetScoutBrowserApprovalResponse,
    InternetScoutConsumerRequest,
    InternetScoutLocalLLMResponse,
    InternetScoutMemoryPromotion,
    InternetScoutMemoryPromotionCandidate,
    InternetScoutMemoryPromotionCreateRequest,
    InternetScoutMemoryPromotionCreateResponse,
    InternetScoutMemoryPromotionReviewRequest,
    InternetScoutMemoryPromotionReviewResponse,
    InternetScoutPlan,
    InternetScoutRequest,
    InternetScoutStoredResponse,
    InternetTool,
    MemoryPromotionStatus,
    PolicyDecision,
    SemanticMemoryCategory,
    SourceReference,
)
from brain.services.internet_scout.browser_runner import (
    BrowserScreenshotStore,
    BrowserTaskRunner,
    PlaywrightBrowserTaskAdapter,
    browser_hourly_run_limit,
    build_browser_task_runner_from_env,
)
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.memory_promotions import (
    MemoryPromotionPolicyError,
    validate_memory_promotion_candidate,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.policy import evaluate_policy, select_tool

__all__ = [
    "BeaconConsumer",
    "BrowserRunObservation",
    "BrowserSandboxPolicy",
    "BrowserScreenshotStore",
    "BrowserTaskRunner",
    "EvidenceClaim",
    "GatewayCrawlResponse",
    "InternetScoutExecutor",
    "InternetScoutBrowserApprovalResponse",
    "InternetScoutBrowserRunRequest",
    "InternetScoutBrowserRunResponse",
    "InternetScoutConsumerRequest",
    "InternetScoutLocalLLMResponse",
    "InternetScoutMemoryPromotion",
    "InternetScoutMemoryPromotionCandidate",
    "InternetScoutMemoryPromotionCreateRequest",
    "InternetScoutMemoryPromotionCreateResponse",
    "InternetScoutMemoryPromotionReviewRequest",
    "InternetScoutMemoryPromotionReviewResponse",
    "InternetScoutOrchestrator",
    "InternetScoutPlan",
    "InternetScoutRequest",
    "InternetScoutStoredResponse",
    "InternetTool",
    "MemoryPromotionPolicyError",
    "MemoryPromotionStatus",
    "PlaywrightBrowserTaskAdapter",
    "PolicyDecision",
    "SemanticMemoryCategory",
    "SourceReference",
    "browser_hourly_run_limit",
    "build_browser_task_runner_from_env",
    "evaluate_policy",
    "select_tool",
    "validate_memory_promotion_candidate",
]
