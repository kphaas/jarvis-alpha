from __future__ import annotations

from brain.services.internet_scout.browser_approvals import (
    browser_task_approval_description,
    browser_task_parameters_hash,
)
from brain.services.internet_scout.models import (
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.policy import evaluate_policy


def test_browser_task_hash_is_stable_and_description_omits_raw_task_text():
    request = InternetScoutRequest(
        query="open example and click the pricing tab",
        urls=["https://public.example.test/start"],
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
    )
    decision = evaluate_policy(request)

    first_hash = browser_task_parameters_hash(request, decision)
    second_hash = browser_task_parameters_hash(request, decision)
    description = browser_task_approval_description(request, decision)

    assert first_hash == second_hash
    assert len(first_hash) == 64
    assert "pricing tab" not in description
    assert "public.example.test" not in description
    assert "Beacon browser-use approval" in description
    assert "urls=1" in description
