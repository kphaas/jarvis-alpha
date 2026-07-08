from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from brain.middleware.jwt_auth import require_auth
from brain.routes.helm_voice import _forward_voice_upload, _read_voice_upload
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

router = APIRouter(prefix="/v1/home/homie", tags=["home-homie"])
logger = get_logger("alpha_brain")

_HOME_GATEWAY_BASE_URL_KEY = "JARVIS_HOME_GATEWAY_BASE_URL"
_HOME_GATEWAY_TOKEN_KEY = "JARVIS_HOME_GATEWAY_TOKEN"
_HOME_GATEWAY_TIMEOUT_S = 15.0
_INTENT_STOP_WORDS = {
    "a",
    "all",
    "an",
    "are",
    "at",
    "for",
    "home",
    "house",
    "is",
    "me",
    "my",
    "of",
    "on",
    "please",
    "set",
    "status",
    "the",
    "to",
    "turn",
    "what",
}


class HomieIntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=400)
    surface: Literal["chat", "voice"] = "chat"


@router.get("/state")
async def get_homie_state(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _request_homie_gateway("GET", "/v1/home/homie/state", request=request)


@router.get("/events/stream")
async def get_homie_events_stream(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> StreamingResponse:
    return StreamingResponse(
        _stream_homie_gateway("/v1/home/homie/events/stream", request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/action")
async def post_homie_action(
    body: dict[str, Any],
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _request_homie_gateway(
        "POST",
        "/v1/home/homie/action",
        request=request,
        body=body,
    )


@router.post("/intent")
async def post_homie_intent(
    body: HomieIntentRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _handle_homie_intent_text(
        body.text, surface=body.surface, request=request
    )


@router.post("/voice-intent")
async def post_homie_voice_intent(
    request: Request,
    file: UploadFile = File(...),
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    data, filename, content_type = await _read_voice_upload(file)
    transcript = await _forward_voice_upload(
        request=request,
        data=data,
        filename=filename,
        content_type=content_type,
    )
    text = str(transcript.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=502, detail="voice_backend_empty_transcript")
    response = await _handle_homie_intent_text(text, surface="voice", request=request)
    response["transcript"] = text
    return response


async def _handle_homie_intent_text(
    text: str,
    *,
    surface: Literal["chat", "voice"],
    request: Request,
) -> dict[str, Any]:
    state_payload = await _request_homie_gateway(
        "GET", "/v1/home/homie/state", request=request
    )
    snapshot = _expect_snapshot(state_payload.get("snapshot"))
    context_index = _optional_context_index(state_payload.get("context"))
    mapping_index = _optional_mapping_index(state_payload.get("mapping"))
    parsed = _parse_intent(text, snapshot, context_index, mapping_index)
    stream = {"path": "/v1/home/homie/events/stream", "transport": "sse"}

    if parsed["kind"] == "read":
        entity = parsed.get("entity")
        if isinstance(entity, dict):
            entity_context = context_index.get(str(entity.get("entity_id", "")), {})
            return {
                "mode": "read",
                "surface": surface,
                "reply": _entity_status_reply(
                    entity, surface=surface, entity_context=entity_context
                ),
                "intent": {"kind": "read", "entity_id": entity.get("entity_id")},
                "entity": entity,
                "stream": stream,
            }
        return {
            "mode": "read",
            "surface": surface,
            "reply": _whole_home_summary(snapshot, context_index, surface=surface),
            "intent": {"kind": "read", "scope": "whole_home"},
            "stream": stream,
        }

    if parsed["kind"] == "unresolved":
        return {
            "mode": "unresolved",
            "surface": surface,
            "reply": _unresolved_reply(surface=surface),
            "intent": {"kind": "unresolved"},
            "stream": stream,
        }

    gateway_result = await _request_homie_gateway(
        "POST",
        "/v1/home/homie/action",
        request=request,
        body=_action_body(parsed),
    )
    response = {
        "mode": gateway_result.get("mode"),
        "surface": surface,
        "reply": _action_reply(gateway_result, surface=surface),
        "intent": {
            "kind": "action",
            "entity_id": parsed["entity"]["entity_id"],
            "service": parsed["service"],
            **(
                {"service_data": parsed["service_data"]}
                if "service_data" in parsed
                else {}
            ),
        },
        "gateway": gateway_result,
        "stream": stream,
    }
    for key in ("plan", "proposal", "approval", "execution"):
        value = gateway_result.get(key)
        if value is not None:
            response[key] = value
    return response


@router.post("/approvals/{approval_id}/review")
async def post_homie_approval_review(
    approval_id: str,
    body: dict[str, Any],
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _request_homie_gateway(
        "POST",
        f"/v1/home/homie/approvals/{approval_id}/review",
        request=request,
        body=body,
    )


@router.post("/approvals/{approval_id}/resume")
async def post_homie_approval_resume(
    approval_id: str,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _request_homie_gateway(
        "POST",
        f"/v1/home/homie/approvals/{approval_id}/resume",
        request=request,
    )


@router.post("/approvals/{approval_id}/execute")
async def post_homie_approval_execute(
    approval_id: str,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    return await _request_homie_gateway(
        "POST",
        f"/v1/home/homie/approvals/{approval_id}/execute",
        request=request,
    )


async def _request_homie_gateway(
    method: str,
    path: str,
    *,
    request: Request,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = _required_config(_HOME_GATEWAY_BASE_URL_KEY)
    gateway_token = _required_config(_HOME_GATEWAY_TOKEN_KEY)
    headers = _gateway_headers(request, gateway_token)
    try:
        async with httpx.AsyncClient(timeout=_HOME_GATEWAY_TIMEOUT_S) as client:
            url = f"{base_url.rstrip('/')}{path}"
            if body is None:
                response = await client.request(method, url, headers=headers)
            else:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=body,
                )
    except httpx.HTTPError as exc:
        logger.warning("homie_gateway_unreachable path=%s error=%s", path, exc)
        raise HTTPException(
            status_code=502, detail="homie_gateway_unreachable"
        ) from exc

    if response.is_success:
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502, detail="homie_gateway_invalid_response"
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=502, detail="homie_gateway_invalid_response"
            )
        return payload

    raise HTTPException(
        status_code=response.status_code,
        detail=_upstream_detail(response),
    )


async def _stream_homie_gateway(
    path: str,
    *,
    request: Request,
) -> AsyncIterator[str]:
    base_url = _required_config(_HOME_GATEWAY_BASE_URL_KEY)
    gateway_token = _required_config(_HOME_GATEWAY_TOKEN_KEY)
    headers = _gateway_headers(request, gateway_token)
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                f"{base_url.rstrip('/')}{path}",
                headers=headers,
            ) as response:
                if not response.is_success:
                    yield _sse_event(
                        "error",
                        {"detail": f"homie_gateway_http_{response.status_code}"},
                    )
                    return
                async for chunk in response.aiter_text():
                    yield chunk
    except httpx.HTTPError as exc:
        logger.warning("homie_gateway_stream_unreachable path=%s error=%s", path, exc)
        yield _sse_event("error", {"detail": "homie_gateway_unreachable"})


def _gateway_headers(request: Request, gateway_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {gateway_token}",
        **_trusted_actor_headers(request),
    }


def _trusted_actor_headers(request: Request) -> dict[str, str]:
    actor_type = str(getattr(request.state, "actor_type", "user") or "user")
    if actor_type != "user":
        raise HTTPException(status_code=403, detail="homie_user_session_required")

    actor_id = str(getattr(request.state, "user_id", "") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    role = str(getattr(request.state, "role", "user") or "user")
    actor_kind = "child" if role == "child" else "adult"
    headers = {
        "X-Actor-Id": actor_id,
        "X-Actor-Kind": actor_kind,
    }
    profile_id = str(getattr(request.state, "profile_id", "") or "").strip()
    if profile_id:
        headers["X-Profile-Id"] = profile_id
    display_name = str(getattr(request.state, "display_name", "") or "").strip()
    if display_name:
        headers["X-Display-Name"] = display_name
    return headers


def _required_config(key: str) -> str:
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value
    try:
        secret_value = get_secret(key).strip()
    except KeyError as exc:
        raise HTTPException(
            status_code=503, detail=f"{key.lower()}_not_configured"
        ) from exc
    if not secret_value:
        raise HTTPException(status_code=503, detail=f"{key.lower()}_not_configured")
    return secret_value


def _sse_event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"


def _parse_intent(
    text: str,
    snapshot: dict[str, dict[str, Any]],
    context_index: dict[str, dict[str, Any]],
    mapping_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_text(text)
    if _is_whole_home_read(normalized):
        return {"kind": "read"}

    entity = _resolve_entity(text, snapshot, context_index, mapping_index or {})
    if _is_read_query(text, normalized):
        if entity is None:
            return {"kind": "read"}
        return {"kind": "read", "entity": entity}

    if entity is None:
        return {"kind": "unresolved"}

    if _contains_any(normalized, ("turn on", "switch on", "enable", "start")):
        return {"kind": "action", "entity": entity, "service": "turn_on"}
    if _contains_any(normalized, ("turn off", "switch off", "disable", "stop")):
        return {"kind": "action", "entity": entity, "service": "turn_off"}

    numeric_value = _extract_numeric_value(normalized)
    if numeric_value is not None:
        entity_id = str(entity.get("entity_id", ""))
        if entity_id.startswith(("number.", "input_number.")):
            value: int | float = (
                int(numeric_value) if numeric_value.is_integer() else numeric_value
            )
            return {
                "kind": "action",
                "entity": entity,
                "service": "set_value",
                "service_data": {"value": value},
            }
        if entity_id.startswith("climate."):
            value = int(numeric_value) if numeric_value.is_integer() else numeric_value
            return {
                "kind": "action",
                "entity": entity,
                "service": "set_temperature",
                "service_data": {"temperature": value},
            }

    entity_id = str(entity.get("entity_id", ""))
    if entity_id.startswith("select."):
        option = _match_entity_option(entity, normalized, attribute_key="options")
        if option is not None:
            return {
                "kind": "action",
                "entity": entity,
                "service": "select_option",
                "service_data": {"option": option},
            }
    if entity_id.startswith("climate."):
        hvac_mode = _match_entity_option(entity, normalized, attribute_key="hvac_modes")
        if hvac_mode is not None:
            return {
                "kind": "action",
                "entity": entity,
                "service": "set_hvac_mode",
                "service_data": {"hvac_mode": hvac_mode},
            }

    return {"kind": "unresolved"}


def _resolve_entity(
    text: str,
    snapshot: dict[str, dict[str, Any]],
    context_index: dict[str, dict[str, Any]],
    mapping_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_text = _normalize_text(text)
    text_tokens = _meaningful_tokens(normalized_text)
    best: dict[str, Any] | None = None
    best_score = 0

    for entity in snapshot.values():
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id:
            continue
        names = [entity_id.replace(".", " ").replace("_", " ")]
        friendly_name = entity.get("friendly_name")
        if isinstance(friendly_name, str) and friendly_name.strip():
            names.insert(0, friendly_name)
        names.extend(_context_names(context_index.get(entity_id)))
        names.extend(_mapping_names(mapping_index.get(entity_id)))

        score = 0
        for name in names:
            normalized_name = _normalize_text(name)
            name_tokens = _meaningful_tokens(normalized_name)
            if not name_tokens:
                continue
            if normalized_name and normalized_name in normalized_text:
                score = max(score, 100 + len(name_tokens))
            overlap = len(text_tokens & name_tokens)
            if overlap:
                score = max(score, overlap * 10 + len(name_tokens))
        if entity_id.lower() in text.lower():
            score = max(score, 200)
        if score > best_score:
            best = entity
            best_score = score

    if best_score < 20:
        return None
    return best


def _is_read_query(text: str, normalized: str) -> bool:
    if text.strip().endswith("?"):
        return True
    return _contains_any(
        normalized,
        ("is ", "are ", "what is", "what s", "status", "how is", "how are"),
    )


def _is_whole_home_read(normalized: str) -> bool:
    return (
        "what s on" in normalized
        or "what is on" in normalized
        or "what lights are on" in normalized
        or "which lights are on" in normalized
    )


def _whole_home_summary(
    snapshot: dict[str, dict[str, Any]],
    context_index: dict[str, dict[str, Any]],
    *,
    surface: Literal["chat", "voice"],
) -> str:
    active_names: list[str] = []
    for entity in snapshot.values():
        state = entity.get("state")
        if not isinstance(state, str) or state not in {"on", "playing", "heat", "cool"}:
            continue
        friendly_name = entity.get("friendly_name")
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        label = (
            friendly_name
            if isinstance(friendly_name, str) and friendly_name
            else entity_id
        )
        active_names.append(
            _entity_label_with_room(
                {"entity_id": entity_id, "friendly_name": label},
                context_index.get(entity_id),
            )
        )

    if not active_names:
        return "Nothing is on right now."

    shown = active_names[:5] if surface == "voice" else active_names[:8]
    names = ", ".join(shown)
    if len(active_names) > len(shown):
        return f"Currently on: {names}, and {len(active_names) - len(shown)} more."
    return f"Currently on: {names}."


def _entity_status_reply(
    entity: dict[str, Any],
    *,
    surface: Literal["chat", "voice"],
    entity_context: dict[str, Any] | None = None,
) -> str:
    label = _entity_label_with_room(entity, entity_context)
    state = entity.get("state")
    if not isinstance(state, str) or not state:
        return f"I found {label}, but its current state is unavailable."
    if surface == "voice":
        return f"{label} is {state}."
    return f"{label} is currently {state}."


def _action_reply(
    gateway_result: dict[str, Any],
    *,
    surface: Literal["chat", "voice"],
) -> str:
    plan = gateway_result.get("plan")
    entity = plan if isinstance(plan, dict) else {}
    label = _entity_label(entity)
    mode = gateway_result.get("mode")
    policy_summary = _policy_summary(entity)
    quiet_hours_note = _quiet_hours_note(entity)
    confirmed_state = _confirmed_state(gateway_result)
    if mode == "executed":
        if isinstance(confirmed_state, dict):
            observed_state = confirmed_state.get("state")
            if isinstance(observed_state, str) and observed_state:
                reply = f"Done. {label} is now {observed_state}."
            else:
                reply = f"Done. {label} was updated."
        else:
            reply = f"Done. {label} was updated."
        if surface == "chat" and policy_summary:
            reply = f"{reply} {policy_summary}"
        if surface == "chat" and quiet_hours_note:
            reply = f"{reply} {quiet_hours_note}"
        return reply
    if mode == "proposal":
        approval = gateway_result.get("approval")
        approval_id = (
            approval.get("approval_id") if isinstance(approval, dict) else None
        )
        if policy_summary:
            prefix = f"{label} needs approval. {policy_summary}"
        else:
            prefix = f"{label} needs approval before I can execute it."
        if isinstance(approval_id, str) and approval_id:
            if surface == "voice":
                return f"{prefix} Request {approval_id} is ready."
            return f"{prefix} Request `{approval_id}` is ready."
        return prefix
    if mode == "denied":
        if policy_summary:
            return f"I can't do that. {policy_summary}"
        reason = (
            entity.get("reason")
            if isinstance(entity.get("reason"), str)
            else "not allowed"
        )
        return f"I can't do that: {reason}."
    return "I could not complete that home action."


def _unresolved_reply(*, surface: Literal["chat", "voice"]) -> str:
    if surface == "voice":
        return (
            "I could not match that to a home device yet. Say the room and device name."
        )
    return (
        "I could not match that to a home device yet. Try the room and device name, "
        "like `turn on kitchen lights`."
    )


def _action_body(parsed: dict[str, Any]) -> dict[str, Any]:
    entity = parsed["entity"]
    body: dict[str, Any] = {
        "entity_id": entity["entity_id"],
        "service": parsed["service"],
    }
    if "service_data" in parsed:
        body["service_data"] = parsed["service_data"]
    return body


def _entity_label(entity: dict[str, Any]) -> str:
    friendly_name = entity.get("friendly_name")
    if isinstance(friendly_name, str) and friendly_name.strip():
        return friendly_name.strip()
    entity_id = entity.get("entity_id")
    if isinstance(entity_id, str) and entity_id:
        return entity_id
    return "That device"


def _entity_label_with_room(
    entity: dict[str, Any], entity_context: dict[str, Any] | None
) -> str:
    label = _entity_label(entity)
    if not isinstance(entity_context, dict):
        return label
    room = entity_context.get("room")
    if not isinstance(room, dict):
        return label
    room_label = room.get("label")
    if not isinstance(room_label, str) or not room_label:
        return label
    if room_label.lower() in label.lower():
        return label
    return f"{label} ({room_label})"


def _expect_snapshot(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="homie_gateway_invalid_response")

    snapshot: dict[str, dict[str, Any]] = {}
    for entity_id, entity in value.items():
        if isinstance(entity_id, str) and isinstance(entity, dict):
            snapshot[entity_id] = entity
    return snapshot


def _optional_context_index(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    context_index: dict[str, dict[str, Any]] = {}
    for entity_id, entity_context in value.items():
        if isinstance(entity_id, str) and isinstance(entity_context, dict):
            context_index[entity_id] = entity_context
    return context_index


def _optional_mapping_index(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    mapped = value.get("mapped")
    if not isinstance(mapped, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for entry in mapped:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str) and entity_id:
            index[entity_id] = entry
    return index


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _extract_numeric_value(text: str) -> float | None:
    match = re.search(r"\b(-?\d+(?:\.\d+)?)\b", text)
    if match is None:
        return None
    return float(match.group(1))


def _match_entity_option(
    entity: dict[str, Any],
    normalized_text: str,
    *,
    attribute_key: str,
) -> str | None:
    attributes = entity.get("attributes")
    if not isinstance(attributes, dict):
        return None
    raw_options = attributes.get(attribute_key)
    if not isinstance(raw_options, list):
        return None

    matches: list[tuple[int, str]] = []
    for raw_option in raw_options:
        if not isinstance(raw_option, str) or not raw_option.strip():
            continue
        normalized_option = _normalize_text(raw_option)
        if not normalized_option:
            continue
        if (
            normalized_text.endswith(normalized_option)
            or f" to {normalized_option}" in normalized_text
        ):
            matches.append((len(normalized_option), raw_option))

    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _normalize_text(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in text.split()
        if token and token not in _INTENT_STOP_WORDS and not token.isdigit()
    }


def _context_names(entity_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(entity_context, dict):
        return []
    names: list[str] = []
    room = entity_context.get("room")
    if isinstance(room, dict):
        label = room.get("label")
        if isinstance(label, str) and label.strip():
            names.append(label)
        aliases = room.get("aliases")
        if isinstance(aliases, list):
            names.extend(
                alias for alias in aliases if isinstance(alias, str) and alias.strip()
            )
    routines = entity_context.get("routines")
    if isinstance(routines, list):
        for routine in routines:
            if not isinstance(routine, dict):
                continue
            label = routine.get("label")
            if isinstance(label, str) and label.strip():
                names.append(label)
            aliases = routine.get("aliases")
            if isinstance(aliases, list):
                names.extend(
                    alias
                    for alias in aliases
                    if isinstance(alias, str) and alias.strip()
                )
    return names


def _mapping_names(mapping: dict[str, Any] | None) -> list[str]:
    if not isinstance(mapping, dict):
        return []
    names: list[str] = []
    for key in ("display_name", "friendly_name"):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value)
    aliases = mapping.get("aliases")
    if isinstance(aliases, list):
        names.extend(
            alias for alias in aliases if isinstance(alias, str) and alias.strip()
        )
    if mapping.get("device_role") == "primary":
        group_label = mapping.get("device_group_label")
        if isinstance(group_label, str) and group_label.strip():
            names.append(group_label)
    return names


def _policy_summary(plan: dict[str, Any]) -> str | None:
    governance = plan.get("governance")
    if not isinstance(governance, dict):
        return None
    summary = governance.get("policy_summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return summary.strip()


def _quiet_hours_note(plan: dict[str, Any]) -> str | None:
    context = plan.get("context")
    if not isinstance(context, dict):
        return None
    quiet_hours = context.get("quiet_hours")
    if not isinstance(quiet_hours, dict) or quiet_hours.get("active") is not True:
        return None
    room = context.get("room")
    room_label = room.get("label") if isinstance(room, dict) else None
    if isinstance(room_label, str) and room_label.strip():
        return f"Quiet hours are active for {room_label}."
    label = quiet_hours.get("label")
    if isinstance(label, str) and label.strip():
        return f"{label} is active."
    return "Quiet hours are active."


def _confirmed_state(gateway_result: dict[str, Any]) -> dict[str, Any] | None:
    direct = gateway_result.get("confirmed_state")
    if isinstance(direct, dict):
        return direct
    execution = gateway_result.get("execution")
    if not isinstance(execution, dict):
        return None
    confirmed_state = execution.get("confirmed_state")
    if isinstance(confirmed_state, dict):
        return confirmed_state
    return None


def _upstream_detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or "homie_gateway_error"
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload
