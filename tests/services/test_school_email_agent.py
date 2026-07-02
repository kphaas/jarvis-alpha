from dataclasses import replace

import pytest

from brain.services.family_school_client import (
    FamilySchoolClient,
    FamilySchoolClientConfigError,
)
from brain.services.school_email_rules import (
    SchoolEmailScanRule,
    _sender_query,
    message_rule_map,
)


def test_sender_query_uses_24_hour_lookback_for_exact_sender() -> None:
    assert _sender_query("teacher@example.com", 1) == (
        "from:teacher@example.com newer_than:1d"
    )


def test_sender_query_supports_domain_rules() -> None:
    assert _sender_query("@mountpisgah.org", 1) == (
        "from:(mountpisgah.org) newer_than:1d"
    )


def _rule(child_member_id: str, query: str) -> SchoolEmailScanRule:
    return SchoolEmailScanRule(
        id=child_member_id,
        child_member_id=child_member_id,
        child_name="Child",
        label="School domain",
        sender_email="@mountpisgahschool.org",
        rule_type="school",
        query=query,
        trusted_sender=True,
    )


@pytest.mark.asyncio
async def test_message_rule_map_dedupes_identical_gmail_queries() -> None:
    class Client:
        calls = 0

        async def list_message_ids(
            self, query: str, max_results: int = 25
        ) -> list[str]:
            self.calls += 1
            assert query == "from:(mountpisgahschool.org) newer_than:1d"
            assert max_results == 25
            return ["gmail-1"]

    first = _rule("child-1", "from:(mountpisgahschool.org) newer_than:1d")
    second = replace(first, id="child-2", child_member_id="child-2")
    client = Client()

    message_rules, queries_run = await message_rule_map(
        gmail=client,
        rules=[first, second],
        max_results=25,
    )

    assert client.calls == 1
    assert queries_run == 1
    assert message_rules == {"gmail-1": [first, second]}


def test_family_school_client_requires_explicit_base_url(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_FAMILY_API_URL", raising=False)

    with pytest.raises(FamilySchoolClientConfigError):
        FamilySchoolClient()


def test_family_school_client_rejects_public_family_url() -> None:
    with pytest.raises(FamilySchoolClientConfigError, match="https tailnet host"):
        FamilySchoolClient("https://family.invalid")
