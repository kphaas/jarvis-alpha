from brain.middleware.approval_classes import classify_route


def test_at0_mail_routes_are_classified() -> None:
    assert classify_route("GET", "/v1/at0-mail/dashboard") == [
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
