"""Beacon internet-scout service contracts.

Beacon is Alpha's internet evidence broker. Brain owns policy, planning, and
stored evidence; Gateway owns guarded public egress and extraction.
"""

from brain.services.internet_scout.models import (
    EvidenceClaim,
    GatewayCrawlResponse,
    InternetScoutBrowserApprovalResponse,
    InternetScoutLocalLLMResponse,
    InternetScoutPlan,
    InternetScoutRequest,
    InternetScoutStoredResponse,
    InternetTool,
    PolicyDecision,
    SourceReference,
)
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.policy import evaluate_policy, select_tool

__all__ = [
    "EvidenceClaim",
    "GatewayCrawlResponse",
    "InternetScoutExecutor",
    "InternetScoutBrowserApprovalResponse",
    "InternetScoutLocalLLMResponse",
    "InternetScoutOrchestrator",
    "InternetScoutPlan",
    "InternetScoutRequest",
    "InternetScoutStoredResponse",
    "InternetTool",
    "PolicyDecision",
    "SourceReference",
    "evaluate_policy",
    "select_tool",
]
