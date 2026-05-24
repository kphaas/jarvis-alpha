from brain.services.school_email_rules import _sender_query


def test_sender_query_uses_24_hour_lookback_for_exact_sender() -> None:
    assert _sender_query("teacher@example.com", 1) == (
        "from:teacher@example.com newer_than:1d"
    )


def test_sender_query_supports_domain_rules() -> None:
    assert _sender_query("@mountpisgah.org", 1) == (
        "from:(mountpisgah.org) newer_than:1d"
    )
