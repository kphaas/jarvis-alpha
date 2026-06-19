#!/usr/bin/env python3
"""Smoke Privacy Agent's synthetic manual workflow without printing secrets."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_TARGET_ID = "beenverified"


class SmokeSkip(RuntimeError):
    """Raised when local configuration is intentionally unavailable."""


@dataclass(frozen=True)
class SmokeContext:
    base_url: str
    token: str
    approval_pin: str | None
    approval_mode: str
    approval_wait_seconds: int
    run_id: str
    target_id: str
    allow_unconfigured: bool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ALPHA_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("PRIVACY_SMOKE_PROFILE", "ken"),
    )
    parser.add_argument(
        "--target-id",
        default=os.getenv("PRIVACY_SMOKE_TARGET_ID", DEFAULT_TARGET_ID),
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv(
            "PRIVACY_SMOKE_TOKEN_SSH_TARGET",
            DEFAULT_TOKEN_SSH_TARGET,
        ),
        help=(
            "SSH target used to generate a target-side user token when "
            "PRIVACY_SMOKE_TOKEN is not set."
        ),
    )
    parser.add_argument(
        "--allow-unconfigured",
        action="store_true",
        default=os.getenv("PRIVACY_SMOKE_ALLOW_UNCONFIGURED", "0") == "1",
    )
    parser.add_argument(
        "--approval-mode",
        choices=("pin", "operator"),
        default=os.getenv("PRIVACY_SMOKE_APPROVAL_MODE", "pin"),
        help=(
            "pin unlocks via /v1/approvals/unlock; operator prints the queue "
            "id and waits for a human to approve in Alpha."
        ),
    )
    parser.add_argument(
        "--approval-wait-seconds",
        type=int,
        default=int(os.getenv("PRIVACY_SMOKE_APPROVAL_WAIT_SECONDS", "600")),
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    try:
        approval_pin = None
        if args.approval_mode == "pin":
            approval_pin = _approval_pin(
                require_explicit=not _is_local_base_url(base_url),
            )
        ctx = SmokeContext(
            base_url=base_url,
            token=_smoke_token(
                profile=args.profile,
                base_url=base_url,
                token_ssh_target=args.token_ssh_target,
            ),
            approval_pin=approval_pin,
            approval_mode=args.approval_mode,
            approval_wait_seconds=max(args.approval_wait_seconds, 1),
            run_id=run_id,
            target_id=args.target_id,
            allow_unconfigured=args.allow_unconfigured,
        )
        result = run_smoke(ctx)
    except SmokeSkip as exc:
        _emit({"status": "skipped", "reason": str(exc)})
        return 2
    except KeyboardInterrupt:
        _emit({"status": "interrupted", "reason": "operator stopped smoke"})
        return 130
    except Exception as exc:
        _emit({"status": "failed", "error": str(exc)})
        return 1

    _emit({"status": "passed", "result": result})
    return 0


def run_smoke(ctx: SmokeContext) -> dict[str, object]:
    """Run one synthetic manual Privacy Agent workflow."""

    client = PrivacySmokeClient(ctx)
    synthetic_email = f"privacy-smoke+{ctx.run_id}@example.test"
    forbidden_values = tuple(
        value for value in (synthetic_email, ctx.approval_pin) if value
    )

    removal = client.call_json("GET", "/v1/privacy/removal-control/summary")
    if removal.get("outbound_enabled") is not False:
        raise RuntimeError("removal control must remain outbound-disabled")

    approval_token = None
    if ctx.approval_mode == "pin":
        if not ctx.approval_pin:
            raise RuntimeError("pin approval mode requires an approval pin")
        approval_token = _unlock_approvals(client, ctx.approval_pin)

    targets = _ensure_targets(client)
    target = _select_target(targets, ctx.target_id)

    subject = client.call_json(
        "POST",
        "/v1/privacy/subjects",
        {
            "display_label": f"privacy-smoke-{ctx.run_id}",
            "role": "adult",
            "jurisdiction": "US_GA",
            "payload": {
                "synthetic": True,
                "smoke_run_id": ctx.run_id,
            },
            "identity_tuples": [
                {
                    "tuple_type": "email",
                    "value": synthetic_email,
                    "label": "synthetic smoke email",
                }
            ],
        },
    )
    _assert_no_forbidden_values("subject", subject, forbidden_values)
    subject_id = _required_str(subject, "subject_id")

    draft = client.call_json(
        "POST",
        f"/v1/privacy/subjects/{subject_id}/case-drafts",
        {"target_ids": [target["id"]]},
    )
    _assert_no_forbidden_values("draft", draft, forbidden_values)
    case_id = _required_str(draft, "case_id")
    if draft.get("action_count") != 1:
        raise RuntimeError("case draft did not create exactly one action")

    submitted = client.call_json(
        "POST",
        f"/v1/privacy/case-drafts/{case_id}/submit-approval",
        {"operator_note": f"synthetic privacy smoke {ctx.run_id}"},
    )
    _assert_no_forbidden_values("submitted", submitted, forbidden_values)
    queue_id = _required_str(submitted, "queue_id")
    if submitted.get("status") != "submitted_for_approval":
        raise RuntimeError("case draft was not submitted for approval")

    if ctx.approval_mode == "operator":
        action = _wait_for_operator_approval(
            client,
            case_id=case_id,
            queue_id=queue_id,
            wait_seconds=ctx.approval_wait_seconds,
        )
    else:
        if not approval_token:
            raise RuntimeError("pin approval mode did not return an approval token")
        decision = client.call_json(
            "POST",
            f"/v1/approvals/{queue_id}/decide",
            {"decision": "approved"},
            extra_headers={"X-Approval-Token": approval_token},
        )
        _assert_no_forbidden_values("decision", decision, forbidden_values)
        if decision.get("queue_id") != queue_id:
            raise RuntimeError("approval decision returned the wrong queue id")
        action = _find_approved_action(client, case_id)

    _assert_no_forbidden_values("approved-action", action, forbidden_values)
    action_id = _required_str(action, "action_id")
    if action.get("status") != "approved":
        raise RuntimeError("approved privacy action did not enter approved state")

    disposition = client.call_json(
        "POST",
        f"/v1/privacy/actions/{action_id}/manual-disposition",
        {
            "disposition": "handled",
            "operator_note": f"synthetic handled smoke {ctx.run_id}",
            "evidence_reference": (
                f"smoke://privacy/automated/{ctx.run_id}/disposition"
            ),
        },
    )
    if disposition.get("event_type") != "sent":
        raise RuntimeError("manual disposition did not record sent event")
    if _required_dict(disposition, "action").get("status") != "sent":
        raise RuntimeError("manual disposition did not move action to sent")

    verification = client.call_json(
        "POST",
        f"/v1/privacy/actions/{action_id}/verification",
        {
            "outcome": "confirmed",
            "operator_note": f"synthetic verified smoke {ctx.run_id}",
            "evidence_reference": (
                f"smoke://privacy/automated/{ctx.run_id}/verification"
            ),
        },
    )
    if verification.get("event_type") != "confirmed":
        raise RuntimeError("verification did not record confirmed event")
    if _required_dict(verification, "action").get("status") != "confirmed":
        raise RuntimeError("verification did not move action to confirmed")

    timeline = client.call_json("GET", f"/v1/privacy/case-drafts/{case_id}/timeline")
    event_types = [
        str(event.get("event_type"))
        for event in timeline.get("events", [])
        if isinstance(event, dict)
    ]
    for expected in ("created", "approval_requested", "approved", "sent", "confirmed"):
        if expected not in event_types:
            raise RuntimeError(f"timeline missing event type: {expected}")

    report = client.call_json("GET", f"/v1/privacy/case-drafts/{case_id}/report")
    manifest = _required_dict(report, "evidence_manifest")
    if manifest.get("status") != "complete":
        raise RuntimeError("case report evidence manifest is not complete")
    if manifest.get("missing_evidence_count") != 0:
        raise RuntimeError("case report has missing evidence")

    for label, payload in (
        ("timeline", timeline),
        ("report", report),
        ("verification", verification),
    ):
        _assert_no_forbidden_values(label, payload, forbidden_values)

    return {
        "run_id": ctx.run_id,
        "target_id": target["id"],
        "case_id": case_id,
        "action_id": action_id,
        "timeline_events": len(event_types),
        "evidence_status": manifest.get("status"),
        "outbound_enabled": removal.get("outbound_enabled"),
    }


class PrivacySmokeClient:
    def __init__(self, ctx: SmokeContext) -> None:
        self._ctx = ctx

    def call_json(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._ctx.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{self._ctx.base_url}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(
                request,
                context=ssl._create_unverified_context(),
                timeout=45,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            if (
                exc.code == 503
                and self._ctx.allow_unconfigured
                and "privacy_scrub_config_missing" in detail
            ):
                raise SmokeSkip("privacy crypto config unavailable")
            raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} returned non-object JSON")
        return payload


def _ensure_targets(client: PrivacySmokeClient) -> list[dict[str, object]]:
    targets = _target_list(client.call_json("GET", "/v1/privacy/targets"))
    if targets:
        return targets

    client.call_json("POST", "/v1/privacy/targets/refresh")
    targets = _target_list(client.call_json("GET", "/v1/privacy/targets"))
    if not targets:
        raise RuntimeError("privacy target registry is empty after refresh")
    return targets


def _target_list(payload: dict[str, object]) -> list[dict[str, object]]:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise RuntimeError("privacy targets response is missing targets")
    if not all(isinstance(target, dict) for target in targets):
        raise RuntimeError("privacy targets response contains non-object target")
    return targets


def _select_target(
    targets: list[dict[str, object]],
    target_id: str,
) -> dict[str, object]:
    for target in targets:
        if target.get("id") == target_id:
            return target
    for target in targets:
        if target.get("category") == "data_broker":
            return target
    raise RuntimeError("no data broker privacy target available")


def _find_approved_action(
    client: PrivacySmokeClient,
    case_id: str,
) -> dict[str, object]:
    query = urlencode({"limit": "50"})
    payload = client.call_json("GET", f"/v1/privacy/actions/approved?{query}")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise RuntimeError("approved action response is missing actions")
    for action in actions:
        if isinstance(action, dict) and action.get("case_id") == case_id:
            return action
    raise RuntimeError("approved action for smoke case was not found")


def _wait_for_operator_approval(
    client: PrivacySmokeClient,
    *,
    case_id: str,
    queue_id: str,
    wait_seconds: int,
) -> dict[str, object]:
    _emit(
        {
            "status": "waiting_for_manual_approval",
            "case_id": case_id,
            "queue_id": queue_id,
            "approve_in": "/v1/approvals",
            "wait_seconds": wait_seconds,
        }
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            return _find_approved_action(client, case_id)
        except RuntimeError:
            time.sleep(5)
    raise RuntimeError(
        f"manual approval was not observed for queue {queue_id} within {wait_seconds}s"
    )


def _unlock_approvals(client: PrivacySmokeClient, pin: str) -> str:
    payload = client.call_json("POST", "/v1/approvals/unlock", {"pin": pin})
    token = payload.get("approval_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("approval unlock did not return a token")
    return token


def _smoke_token(
    *,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    token = os.getenv("PRIVACY_SMOKE_TOKEN")
    if token:
        return token

    if _is_local_base_url(base_url):
        return _local_smoke_token(profile=profile)

    if token_ssh_target:
        generated = subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                token_ssh_target,
                "cd ~/jarvis-alpha && .venv/bin/python scripts/gen_test_token.py "
                f"{shlex.quote(profile)}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not generated:
            raise RuntimeError("target token generation returned no token")
        return generated

    raise RuntimeError(
        "set PRIVACY_SMOKE_TOKEN or PRIVACY_SMOKE_TOKEN_SSH_TARGET for privacy smoke"
    )


def _local_smoke_token(*, profile: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    python_bin = os.getenv("PYTHON_BIN", str(repo_root / ".venv/bin/python"))
    generated = subprocess.check_output(
        [python_bin, str(repo_root / "scripts/gen_test_token.py"), profile],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not generated:
        raise RuntimeError("test token generation returned no token")
    return generated


def _approval_pin(*, require_explicit: bool = False) -> str:
    pin = os.getenv("PRIVACY_SMOKE_APPROVAL_PIN")
    if pin:
        return pin
    if require_explicit:
        raise SmokeSkip(
            "set PRIVACY_SMOKE_APPROVAL_PIN for remote approval smoke; "
            "ALPHA_PIN fallback is disabled"
        )

    secrets = _read_secrets(Path.home() / "jarvis" / ".secrets")
    pin = secrets.get("PRIVACY_SMOKE_APPROVAL_PIN") or secrets.get("ALPHA_PIN")
    if pin:
        return pin

    raise SmokeSkip("set PRIVACY_SMOKE_APPROVAL_PIN or ALPHA_PIN for approval smoke")


def _read_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _assert_no_forbidden_values(
    label: str,
    payload: dict[str, object],
    forbidden_values: tuple[str, ...],
) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in forbidden_values:
        if forbidden and forbidden in serialized:
            raise RuntimeError(f"{label} response leaked a forbidden value")


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"response missing string field: {key}")
    return value


def _required_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"response missing object field: {key}")
    return value


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
