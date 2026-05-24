import base64
from datetime import datetime, timezone

from brain.services.gmail_client import parse_gmail_message


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def test_parse_gmail_message_extracts_headers_and_plain_body() -> None:
    message = parse_gmail_message(
        {
            "id": "msg-1",
            "threadId": "thread-1",
            "historyId": "42",
            "snippet": "School concert",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Mount Pisgah <news@mountpisgah.org>"},
                    {"name": "Subject", "value": "Lower School Concert"},
                    {"name": "Date", "value": "Fri, 22 May 2026 13:30:00 -0400"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _encoded("Concert is May 27 at 6:30pm.")},
                    }
                ],
            },
        }
    )

    assert message.gmail_message_id == "msg-1"
    assert message.sender == "Mount Pisgah <news@mountpisgah.org>"
    assert message.subject == "Lower School Concert"
    assert message.received_at == datetime(2026, 5, 22, 17, 30, tzinfo=timezone.utc)
    assert message.body_text == "Concert is May 27 at 6:30pm."
    assert len(message.body_sha256) == 64


def test_parse_gmail_message_uses_html_when_plain_missing() -> None:
    message = parse_gmail_message(
        {
            "id": "msg-2",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": _encoded("<p>Mount Pisgah<br>May 28</p>")},
                    }
                ],
            },
        }
    )

    assert "Mount Pisgah" in message.body_text
    assert "May 28" in message.body_text
