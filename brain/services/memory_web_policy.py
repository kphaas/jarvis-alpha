"""Memory-first policy for Ask web suggestions."""

from __future__ import annotations

import re

from brain.services.internet_scout.web_suggestion import WebSuggestion

LOCAL_WEB_HOWTO_RE = re.compile(
    r"\bhow\s+(?:do|can|should)\s+i\b[^.!?\n]{0,120}"
    r"\b(?:make\s+you\s+)?(?:search|browse|use\s+(?:the\s+)?web|"
    r"access\s+(?:the\s+)?internet|turn\s+on\s+(?:web\s+search|beacon)|"
    r"enable\s+(?:web\s+search|beacon)|use\s+beacon)\b",
    re.IGNORECASE,
)
LOCAL_SELF_CAPABILITY_RE = re.compile(
    r"\b(?:what\s+can\s+you\s+do|what\s+you\s+can\s+do|"
    r"what\s+are\s+your\s+capabilit(?:y|ies)|"
    r"(?:your\s+)?current\s+capabilit(?:y|ies)|"
    r"can\s+you\s+know\s+yourself|know\s+yourself|"
    r"what\s+do\s+you\s+know\s+about\s+me)\b",
    re.IGNORECASE,
)
CURRENT_FACT_SHORT_CIRCUIT_RE = re.compile(
    r"\b("
    r"today|tomorrow|tonight|yesterday|latest|current|recent|right\s+now|"
    r"this\s+week|this\s+month|next|what\s+time|when|schedule|score|status|"
    r"weather|news|price|market|ceo|release\s+notes|changelog|version|"
    r"game|match|fixture|kick\s*off|opponent|play|playing|standings|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r")\b",
    re.IGNORECASE,
)
MEMORY_RECALL_QUERY_RE = re.compile(
    r"\b("
    r"memory|memories|remember|remembered|saved|stored|approved\s+facts?|"
    r"in\s+memory|from\s+memory"
    r")\b",
    re.IGNORECASE,
)
PERSONAL_PROFILE_MEMORY_QUERY_RE = re.compile(
    r"\b("
    r"ken|me|my|profile|career|resume|work|background|facts?"
    r")\b",
    re.IGNORECASE,
)
EXPLICIT_WEB_QUERY_RE = re.compile(
    r"\b("
    r"web|internet|online|search|browse|look\s+up|official\s+"
    r"(?:site|source|docs?|documentation)|website"
    r")\b",
    re.IGNORECASE,
)


def should_short_circuit_web_suggestion(suggestion: WebSuggestion | None) -> bool:
    if not suggestion:
        return False
    if suggestion.reason == "sports_schedule_likely":
        return True
    if suggestion.reason != "current_information_likely":
        return False

    query = " ".join(suggestion.query.split())
    if LOCAL_WEB_HOWTO_RE.search(query) or LOCAL_SELF_CAPABILITY_RE.search(query):
        return False
    return bool(CURRENT_FACT_SHORT_CIRCUIT_RE.search(query))


def should_prefer_memory_over_web_suggestion(
    *,
    user_msg: str,
    memory_context: str,
    web_suggestion: WebSuggestion | None,
    internet_context: object | None,
) -> bool:
    if not memory_context or not web_suggestion or internet_context:
        return False
    if web_suggestion.reason == "sports_schedule_likely":
        return False

    query = " ".join(user_msg.split())
    if EXPLICIT_WEB_QUERY_RE.search(query):
        return False
    return bool(
        MEMORY_RECALL_QUERY_RE.search(query)
        and PERSONAL_PROFILE_MEMORY_QUERY_RE.search(query)
    )
