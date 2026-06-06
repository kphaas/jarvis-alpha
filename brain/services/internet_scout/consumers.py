"""Consumer-specific Beacon integration policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from brain.services.internet_scout.models import (
    BeaconConsumer,
    InternetScoutConsumerRequest,
    InternetScoutRequest,
    InternetTool,
    Sensitivity,
)
from brain.services.internet_scout.policy import select_tool


class BeaconConsumerPolicyError(ValueError):
    """Raised when a consumer request violates its Beacon boundary."""


@dataclass(frozen=True, slots=True)
class BeaconConsumerPolicy:
    requester: str
    sensitivity: Sensitivity
    allowed_tools: frozenset[InternetTool]


CONSUMER_POLICIES: dict[BeaconConsumer, BeaconConsumerPolicy] = {
    "forge": BeaconConsumerPolicy(
        requester="forge",
        sensitivity="normal",
        allowed_tools=frozenset(
            {
                InternetTool.SEARCH,
                InternetTool.FETCH,
                InternetTool.EXTRACT,
                InternetTool.CRAWL,
            }
        ),
    ),
    "family": BeaconConsumerPolicy(
        requester="family",
        sensitivity="minor",
        allowed_tools=frozenset(
            {
                InternetTool.SEARCH,
                InternetTool.FETCH,
                InternetTool.EXTRACT,
            }
        ),
    ),
    "financial": BeaconConsumerPolicy(
        requester="financial",
        sensitivity="financial",
        allowed_tools=frozenset(
            {
                InternetTool.SEARCH,
                InternetTool.FETCH,
                InternetTool.EXTRACT,
            }
        ),
    ),
}


def build_consumer_internet_request(
    consumer: str,
    request: InternetScoutConsumerRequest,
) -> InternetScoutRequest:
    policy = _consumer_policy(consumer)
    scout_request = InternetScoutRequest(
        query=request.query,
        urls=request.urls,
        tool_hint=request.tool_hint,
        max_pages=request.max_pages,
        max_depth=request.max_depth,
        needs_interaction=request.needs_interaction,
        sensitivity=policy.sensitivity,
        requester=policy.requester,
    )
    selected_tool = select_tool(scout_request)
    if selected_tool not in policy.allowed_tools:
        raise BeaconConsumerPolicyError("consumer_tool_not_allowed")
    return scout_request


def _consumer_policy(consumer: str) -> BeaconConsumerPolicy:
    if consumer not in CONSUMER_POLICIES:
        raise BeaconConsumerPolicyError("consumer_not_supported")
    return CONSUMER_POLICIES[cast(BeaconConsumer, consumer)]
