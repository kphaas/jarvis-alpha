from brain.middleware.approval_classes import classify_route


def test_at0_mail_routes_are_classified() -> None:
    assert classify_route("GET", "/v1/at0-mail/dashboard") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/at0-mail/health") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/at0-mail/mailboxes") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/at0-mail/spark-profile") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/at0-mail/messages") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/at0-mail/drafts") == [
        "read",
        "security_read",
    ]
    assert classify_route("POST", "/v1/at0-mail/scan") == [
        "write",
        "external_call",
    ]
    assert classify_route("POST", "/v1/at0-mail/drafts/abc/status") == [
        "write",
        "security_write",
    ]
    assert classify_route("POST", "/v1/at0-mail/drafts/abc/send") == [
        "write",
        "security_write",
        "external_call",
        "email_send",
    ]


def test_herald_social_routes_are_classified() -> None:
    assert classify_route("GET", "/v1/herald/social/platforms") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/herald/social/drafts") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/herald/social/linkedin/cadence") == [
        "read",
        "security_read",
    ]
    assert classify_route("POST", "/v1/herald/social/drafts") == [
        "write",
        "security_write",
    ]
    assert classify_route("POST", "/v1/herald/social/linkedin/weekly") == [
        "write",
        "security_write",
    ]
    assert classify_route("POST", "/v1/herald/social/drafts/abc/status") == [
        "write",
        "security_write",
    ]
    assert classify_route("POST", "/v1/herald/social/drafts/abc/schedule") == [
        "write",
        "security_write",
    ]
    assert classify_route("POST", "/v1/herald/social/drafts/abc/publish/manual") == [
        "write",
        "security_write",
    ]
