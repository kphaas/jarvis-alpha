"""Shared official-host helpers for Beacon planning and source-quality checks."""

from __future__ import annotations

import re

_OFFICIAL_HOSTS_BY_TERM: dict[str, tuple[str, ...]] = {
    "openai": ("openai.com", "platform.openai.com", "docs.openai.com"),
    "github": ("github.com", "docs.github.com"),
    "stripe": ("stripe.com", "docs.stripe.com"),
    "anthropic": ("anthropic.com", "docs.anthropic.com"),
    "brave": (
        "brave.com",
        "search.brave.com",
        "api.search.brave.com",
        "api-dashboard.search.brave.com",
        "docs.brave.com",
    ),
    "google": ("google.com", "developers.google.com", "cloud.google.com"),
    "microsoft": ("microsoft.com", "learn.microsoft.com"),
    "apple": ("apple.com", "developer.apple.com"),
    "aws": ("aws.amazon.com", "docs.aws.amazon.com"),
    "amazon": ("amazon.com", "aws.amazon.com", "docs.aws.amazon.com"),
    "cloudflare": ("cloudflare.com", "developers.cloudflare.com"),
    "perplexity": ("perplexity.ai", "docs.perplexity.ai"),
}

_COMPARISON_SPLIT_RE = re.compile(
    r"\s+(?:vs\.?|versus|and|against|to)\s+",
    flags=re.IGNORECASE,
)
_COMPARISON_SCOPE_RE = re.compile(
    r"\b(?:for|when|while|with|using|then)\b|[.?!]",
    flags=re.IGNORECASE,
)


def normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def domain_tokens(query: str) -> list[str]:
    tokens = re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", query)
    return [token.strip(".").lower() for token in tokens]


def comparison_targets(query: str) -> list[str]:
    scoped = re.sub(
        r"^\s*(?:compare|comparison\s+of)\s+",
        "",
        query,
        count=1,
        flags=re.IGNORECASE,
    )
    parts = _COMPARISON_SPLIT_RE.split(scoped)
    targets: list[str] = []
    for part in parts:
        target = part.strip()
        target = re.sub(
            r"^\s*(?:find|show|get)\s+",
            "",
            target,
            flags=re.IGNORECASE,
        )
        target = re.sub(
            r"^\s*(?:official\s+)?(?:vendor\s+)?(?:documentation|docs)(?:\s+pages?)?\s+for\s+",
            "",
            target,
            flags=re.IGNORECASE,
        )
        target = _COMPARISON_SCOPE_RE.split(target, maxsplit=1)[0]
        target = re.sub(
            r"\b(?:cite|cited|independent|sources?|official|documentation|docs)\b",
            "",
            target,
            flags=re.IGNORECASE,
        ).strip(" ,;:-")
        if target:
            targets.append(target)
    if len(targets) < 2:
        return []
    return _dedupe_strings(targets)[:2]


def official_hosts_for_target(target: str) -> list[str]:
    normalized = normalize_query(target)
    hosts: list[str] = []
    for term, term_hosts in _OFFICIAL_HOSTS_BY_TERM.items():
        if term in normalized:
            hosts.extend(term_hosts)
    return _dedupe_strings(hosts)


def required_official_host_groups(query: str | None) -> list[list[str]]:
    text = query or ""
    targets = comparison_targets(text)
    if not targets:
        return []
    groups: list[list[str]] = []
    for target in targets:
        hosts = official_hosts_for_target(target)
        if hosts:
            groups.append(hosts)
    return _dedupe_groups(groups)


def required_official_hosts(query: str | None) -> list[str]:
    normalized = normalize_query(query or "")
    hosts: list[str] = []
    for group in required_official_host_groups(query):
        hosts.extend(group)
    if not hosts:
        for term, official_hosts in _OFFICIAL_HOSTS_BY_TERM.items():
            if term in normalized:
                hosts.extend(official_hosts)
    hosts.extend(domain_tokens(normalized))
    return _dedupe_strings(hosts)


def covered_official_host_groups(
    *,
    accepted_hosts: list[str],
    required_groups: list[list[str]],
) -> int:
    if not required_groups:
        return 0
    covered = 0
    for group in required_groups:
        if any(_host_matches_required(host, tuple(group)) for host in accepted_hosts):
            covered += 1
    return covered


def host_matches_required(
    host: str, required_hosts: list[str] | tuple[str, ...]
) -> bool:
    return _host_matches_required(host, tuple(required_hosts))


def _host_matches_required(host: str, required_hosts: tuple[str, ...]) -> bool:
    normalized_host = host.lower().strip(".")
    for required in required_hosts:
        if normalized_host == required:
            return True
        if required.count(".") == 1 and normalized_host == f"www.{required}":
            return True
        if required.count(".") > 1 and normalized_host.endswith(f".{required}"):
            return True
    return False


def _dedupe_groups(groups: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[list[str]] = []
    for group in groups:
        normalized_group = tuple(_dedupe_strings(group))
        if not normalized_group or normalized_group in seen:
            continue
        seen.add(normalized_group)
        deduped.append(list(normalized_group))
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip(".").lower() for value in values if value))
