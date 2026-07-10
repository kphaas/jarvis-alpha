"""MCP tool trust-boundary helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from brain.middleware.approval_classes import classify_route, determine_risk_tier

MCP_TOOL_BOUNDARY_SCHEMA_VERSION = "mcp_tool_boundary.v1"
MCP_TOOL_RESULT_SCHEMA_VERSION = "mcp_tool_result_boundary.v1"
_RISK_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
_PROMPT_INJECTION_RE = re.compile(
    r"(?is)\b("
    r"ignore\s+(?:previous|prior|all|above)\s+instructions?|"
    r"disregard\s+(?:safety|guardrails|rules|policy|instructions?)|"
    r"developer\s+message|system\s+prompt|system\s*[:>]\s*override|"
    r"you\s+are\s+now\s+(?:admin|root|system)|"
    r"follow\s+(?:these|the)\s+instructions?"
    r")\b|<\|im_start\|>|<\|im_end\|>|\"role\"\s*:\s*\"system\""
)


@dataclass(frozen=True)
class MCPToolBoundary:
    tool_name: str
    route: str
    approval_policy: str
    contract_risk_tier: str
    route_action_classes: tuple[str, ...]
    route_risk_tier: str
    effective_risk_tier: str
    approval_required: bool
    requires_existing_approval: bool
    can_invoke_without_human_approval: bool
    allowed_output_fields: tuple[str, ...]
    blocked_by: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, object]:
        return {
            "schema_version": MCP_TOOL_BOUNDARY_SCHEMA_VERSION,
            "tool_name": self.tool_name,
            "route": self.route,
            "approval_policy": self.approval_policy,
            "contract_risk_tier": self.contract_risk_tier,
            "route_action_classes": list(self.route_action_classes),
            "route_risk_tier": self.route_risk_tier,
            "effective_risk_tier": self.effective_risk_tier,
            "approval_required": self.approval_required,
            "requires_existing_approval": self.requires_existing_approval,
            "can_invoke_without_human_approval": self.can_invoke_without_human_approval,
            "raw_tool_output_is_untrusted": True,
            "instructions_inside_tool_results_are_data": True,
            "allowed_output_fields": list(self.allowed_output_fields),
            "blocked_by": list(self.blocked_by),
        }


@dataclass(frozen=True)
class MCPToolResultEnvelope:
    tool_name: str
    sanitized_result: dict[str, object]
    blocked_instruction_count: int
    dropped_field_count: int

    def to_metadata(self) -> dict[str, object]:
        return {
            "schema_version": MCP_TOOL_RESULT_SCHEMA_VERSION,
            "tool_name": self.tool_name,
            "content_is_data": True,
            "instructions_inside_result_ignored": True,
            "raw_tool_output_is_untrusted": True,
            "blocked_instruction_count": self.blocked_instruction_count,
            "dropped_field_count": self.dropped_field_count,
            "risk_markers": (
                ["mcp_prompt_injection_pattern_detected"]
                if self.blocked_instruction_count
                else []
            ),
            "sanitized_result": self.sanitized_result,
        }


def boundary_from_contract_tool(tool: Mapping[str, object]) -> MCPToolBoundary:
    method, path = _route_parts(str(tool.get("route") or ""))
    output_fields = tool.get("output_fields")
    allowed_output_fields = (
        tuple(str(field) for field in output_fields)
        if isinstance(output_fields, list)
        else ()
    )
    route_action_classes = (
        tuple(classify_route(method, path)) if method and path else ()
    )
    route_risk_tier = (
        determine_risk_tier(list(route_action_classes))
        if route_action_classes
        else "T5"
    )
    contract_risk_tier = str(tool.get("risk_tier") or "T5")
    effective_risk_tier = _max_risk_tier(contract_risk_tier, route_risk_tier)
    approval_policy = str(tool.get("approval") or "unknown")
    requires_existing_approval = (
        approval_policy == "requires_existing_approved_queue_id"
    )
    approval_required = approval_policy != "not_required" or effective_risk_tier in {
        "T4",
        "T5",
    }
    blocked_by: list[str] = []
    if not method or not path:
        blocked_by.append("missing_route")
    if "unclassified" in route_action_classes:
        blocked_by.append("unclassified_route")
    if approval_policy == "unknown":
        blocked_by.append("missing_approval_policy")
    if not allowed_output_fields:
        blocked_by.append("missing_output_fields")

    return MCPToolBoundary(
        tool_name=str(tool.get("name") or "unknown"),
        route=str(tool.get("route") or ""),
        approval_policy=approval_policy,
        contract_risk_tier=contract_risk_tier,
        route_action_classes=route_action_classes,
        route_risk_tier=route_risk_tier,
        effective_risk_tier=effective_risk_tier,
        approval_required=approval_required,
        requires_existing_approval=requires_existing_approval,
        can_invoke_without_human_approval=(not approval_required and not blocked_by),
        allowed_output_fields=allowed_output_fields,
        blocked_by=tuple(blocked_by),
    )


def boundary_registry_from_contract(
    contract: Mapping[str, object],
) -> list[dict[str, object]]:
    tools = contract.get("tools", [])
    if not isinstance(tools, list):
        return []
    return [
        boundary_from_contract_tool(tool).to_metadata()
        for tool in tools
        if isinstance(tool, Mapping)
    ]


def sanitize_mcp_tool_result(
    *,
    boundary: MCPToolBoundary,
    result: Mapping[str, object],
    max_text_chars: int = 2000,
) -> MCPToolResultEnvelope:
    sanitized: dict[str, object] = {}
    blocked_instruction_count = 0
    dropped_field_count = 0
    allowed = set(boundary.allowed_output_fields)
    for key, value in result.items():
        if key not in allowed:
            dropped_field_count += 1
            continue
        clean_value, blocked = _sanitize_value(value, max_text_chars=max_text_chars)
        sanitized[str(key)] = clean_value
        blocked_instruction_count += blocked

    return MCPToolResultEnvelope(
        tool_name=boundary.tool_name,
        sanitized_result=sanitized,
        blocked_instruction_count=blocked_instruction_count,
        dropped_field_count=dropped_field_count,
    )


def _sanitize_value(value: object, *, max_text_chars: int) -> tuple[object, int]:
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        if _PROMPT_INJECTION_RE.search(text):
            return "[blocked untrusted MCP tool text]", 1
        return text[:max_text_chars], 0
    if isinstance(value, list):
        cleaned: list[object] = []
        blocked_count = 0
        for item in value[:50]:
            clean_item, blocked = _sanitize_value(item, max_text_chars=max_text_chars)
            cleaned.append(clean_item)
            blocked_count += blocked
        return cleaned, blocked_count
    if isinstance(value, Mapping):
        cleaned_dict: dict[str, object] = {}
        blocked_count = 0
        for key, item in list(value.items())[:50]:
            clean_item, blocked = _sanitize_value(item, max_text_chars=max_text_chars)
            cleaned_dict[str(key)[:80]] = clean_item
            blocked_count += blocked
        return cleaned_dict, blocked_count
    if isinstance(value, (bool, int, float)) or value is None:
        return value, 0
    return str(value)[:max_text_chars], 0


def _route_parts(route: str) -> tuple[str, str]:
    parts = route.strip().split(" ", maxsplit=1)
    if len(parts) != 2:
        return "", ""
    return parts[0].upper(), parts[1].strip()


def _max_risk_tier(left: str, right: str) -> str:
    left_score = _RISK_ORDER.get(left, _RISK_ORDER["T5"])
    right_score = _RISK_ORDER.get(right, _RISK_ORDER["T5"])
    return left if left_score >= right_score else right
