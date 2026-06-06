from __future__ import annotations

import pytest

from brain.services.internet_scout.consumers import (
    BeaconConsumerPolicyError,
    build_consumer_internet_request,
)
from brain.services.internet_scout.models import (
    InternetScoutConsumerRequest,
    InternetTool,
)


def test_forge_consumer_allows_bounded_crawl_with_normal_sensitivity():
    request = build_consumer_internet_request(
        "forge",
        InternetScoutConsumerRequest(
            urls=["https://public.example.test/docs"],
            max_pages=2,
            max_depth=1,
        ),
    )

    assert request.requester == "forge"
    assert request.sensitivity == "normal"
    assert request.max_pages == 2
    assert request.max_depth == 1


def test_family_consumer_forces_minor_sensitivity_and_blocks_browser():
    with pytest.raises(BeaconConsumerPolicyError) as exc:
        build_consumer_internet_request(
            "family",
            InternetScoutConsumerRequest(
                urls=["https://public.example.test/calendar"],
                tool_hint=InternetTool.BROWSER_USE,
                needs_interaction=True,
            ),
        )

    assert str(exc.value) == "consumer_tool_not_allowed"


def test_financial_consumer_forces_financial_sensitivity_and_blocks_crawl():
    with pytest.raises(BeaconConsumerPolicyError) as exc:
        build_consumer_internet_request(
            "financial",
            InternetScoutConsumerRequest(
                urls=["https://public.example.test/markets"],
                max_pages=2,
            ),
        )

    assert str(exc.value) == "consumer_tool_not_allowed"


def test_unknown_consumer_is_rejected():
    with pytest.raises(BeaconConsumerPolicyError) as exc:
        build_consumer_internet_request(
            "unknown",
            InternetScoutConsumerRequest(query="source-backed fact"),
        )

    assert str(exc.value) == "consumer_not_supported"
