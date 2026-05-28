"""Static guard: Brain must never make public-internet calls directly.

V2 §1 invariant: all cloud egress goes through Gateway (jarvis-gateway, Tailscale
mesh). Brain is allowed to talk to:

  * localhost / 127.0.0.1 (Ollama, local services)
  * The Tailscale mesh (`*.tail40ed36.ts.net`, `jarvis-*` hostnames)
  * Gateway (via `GATEWAY_URL` / `ALPHA_GATEWAY_URL` env)
  * Internal env-resolved URLs (`JARVIS_FAMILY_API_URL` etc — operator
    controls whether they're internal or external; out-of-scope here)

Brain must NOT have literal `https?://<public-host>` strings in source.

This test scans every `*.py` file under `brain/` for literal URLs and rejects
any whose host isn't in the allowlist. Each currently-known violation has a
strict xfail marker — fixing one (moving the call behind Gateway) flips it
from xfail to xpass, which fails the test and forces removal from
KNOWN_VIOLATIONS. That keeps the TD list honest.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAIN_DIR = REPO_ROOT / "brain"

# Hosts Brain is allowed to talk to directly.
ALLOWED_HOST_EXACT = {"127.0.0.1", "localhost", "0.0.0.0"}
ALLOWED_HOST_SUFFIX = (".tail40ed36.ts.net",)
ALLOWED_HOST_PREFIX = ("jarvis-",)

URL_RE = re.compile(r"https?://[^\s'\"<>{}\\]+", re.IGNORECASE)
# Treat `{foo}` placeholders (f-strings) as resolved-elsewhere; only the literal
# host portion before the first interpolation marker matters for static analysis.
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class UrlFinding:
    file_path: str  # relative to repo root, posix
    line_number: int
    url_literal: str
    host: str


# Each entry is the (relative_posix_path, host) of a known PUBLIC_INTERNET
# violation. The strict xfail tests below name each one — when the call is
# moved behind Gateway and the literal disappears, the xfail flips to xpass
# and the corresponding test fails, forcing the entry to be removed here.
KNOWN_VIOLATIONS: tuple[tuple[str, str], ...] = (
    ("brain/routes/dev.py", "api.github.com"),
    ("brain/services/gmail_client.py", "oauth2.googleapis.com"),
    ("brain/services/gmail_client.py", "gmail.googleapis.com"),
    ("brain/routes/costs.py", "api.anthropic.com"),
    ("brain/routes/costs.py", "cloudbilling.googleapis.com"),
)

# Literals that LOOK like URLs but aren't actually network egress targets:
#   * docstring/example URLs (placeholder hosts like `host`, `example.com`)
#   * OAuth 2.0 scope identifiers (URIs used as permission strings, never fetched)
#   * honeypot response bodies (fake content returned to attackers, never fetched)
# Maintaining this allowlist explicitly is better than heuristic suppression —
# anything new that looks like egress fails CI until it's either fixed or
# explicitly classified.
KNOWN_NON_EGRESS: tuple[tuple[str, str], ...] = (
    # docstring example: `_extract_domain("https://host:port/path")`
    ("brain/routes/mesh.py", "host"),
    # OAuth scope identifier passed to service_account credentials
    ("brain/routes/costs.py", "www.googleapis.com"),
    # honeypot fake .git/config response body
    ("brain/routes/honeypot.py", "github.com"),
    # honeypot fake debug API response body
    ("brain/routes/honeypot.py", "internal.fake.local"),
)


def _allowed(host: str) -> bool:
    if not host:
        return False
    host_l = host.lower()
    return (
        host_l in ALLOWED_HOST_EXACT
        or any(host_l.endswith(suf) for suf in ALLOWED_HOST_SUFFIX)
        or any(host_l.startswith(pre) for pre in ALLOWED_HOST_PREFIX)
    )


def _python_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if ".venv" in path.parts:
            continue
        yield path


def _string_literals_with_lines(source: str, path: Path) -> list[tuple[str, int]]:
    """Walk AST and yield (literal_text, line_number) for every string constant."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.value, node.lineno))
        elif isinstance(node, ast.JoinedStr):
            # f-string: collect literal parts and synthesize the prefix
            # (anything up to the first {placeholder} is treated as the literal
            # host string for static analysis).
            line = node.lineno
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                else:
                    parts.append("{}")
                    break
            out.append(("".join(parts), line))
    return out


def _scan_brain_for_url_findings() -> list[UrlFinding]:
    findings: list[UrlFinding] = []
    for py in _python_files(BRAIN_DIR):
        try:
            source = py.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py.relative_to(REPO_ROOT).as_posix()
        for literal, line in _string_literals_with_lines(source, py):
            for match in URL_RE.finditer(literal):
                url = match.group(0)
                # Strip placeholder paths after the host for parsing.
                host_only = PLACEHOLDER_RE.sub("", url).rstrip("/")
                try:
                    parsed = urlparse(host_only)
                except ValueError:
                    continue
                host = parsed.hostname or ""
                if not host:
                    continue
                if _allowed(host):
                    continue
                findings.append(
                    UrlFinding(
                        file_path=rel,
                        line_number=line,
                        url_literal=url,
                        host=host,
                    )
                )
    return findings


def test_no_new_public_internet_urls_in_brain():
    findings = _scan_brain_for_url_findings()
    known = set(KNOWN_VIOLATIONS) | set(KNOWN_NON_EGRESS)
    unknown = [f for f in findings if (f.file_path, f.host) not in known]
    assert not unknown, (
        "New public-internet URL(s) found in brain/ — Brain must route via Gateway. "
        "If a finding is genuinely not network egress (docstring, OAuth scope, "
        "honeypot response body), add it to KNOWN_NON_EGRESS. Otherwise it's a "
        "violation and goes in KNOWN_VIOLATIONS with a strict-xfail test.\n"
        "Findings:\n"
        + "\n".join(
            f"  {f.file_path}:{f.line_number}  →  {f.host}  ({f.url_literal!r})"
            for f in unknown
        )
    )


def test_known_violations_still_present():
    """If a known violation has been fixed (URL no longer literal in brain/), this
    test fails so KNOWN_VIOLATIONS gets updated. Keeps the TD list honest."""
    findings = _scan_brain_for_url_findings()
    found = {(f.file_path, f.host) for f in findings}
    missing = [(p, h) for (p, h) in KNOWN_VIOLATIONS if (p, h) not in found]
    assert not missing, (
        "Known violation(s) no longer present in source — remove from "
        "KNOWN_VIOLATIONS and the corresponding xfail test:\n"
        + "\n".join(f"  {p}  →  {h}" for (p, h) in missing)
    )


# -----------------------------------------------------------------------------
# Strict xfail markers for each documented violation. Each is a separate test
# so the failure mode is precise: when the underlying call is moved behind
# Gateway and the literal disappears, that one xfail flips to xpass (= test
# fails because strict=True) and forces the cleanup commit to remove both the
# entry from KNOWN_VIOLATIONS and the corresponding test below.
# -----------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TD: brain/routes/dev.py:116 calls https://api.github.com directly. "
        "Move behind Gateway /v1/cloud/github proxy. (Audit P0 finding, "
        "deferred from Session 1 scope.)"
    ),
)
def test_dev_route_does_not_call_github_directly():
    findings = _scan_brain_for_url_findings()
    bad = [
        f
        for f in findings
        if f.file_path == "brain/routes/dev.py" and f.host == "api.github.com"
    ]
    assert not bad, f"dev.py still calls api.github.com: {bad}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TD: brain/services/gmail_client.py calls oauth2.googleapis.com directly. "
        "Move OAuth refresh behind Gateway /v1/cloud/google_oauth proxy."
    ),
)
def test_gmail_client_does_not_call_google_oauth_directly():
    findings = _scan_brain_for_url_findings()
    bad = [
        f
        for f in findings
        if f.file_path == "brain/services/gmail_client.py"
        and f.host == "oauth2.googleapis.com"
    ]
    assert not bad, f"gmail_client still calls oauth2.googleapis.com: {bad}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TD: brain/services/gmail_client.py calls gmail.googleapis.com directly. "
        "Move Gmail API calls behind Gateway /v1/cloud/gmail proxy."
    ),
)
def test_gmail_client_does_not_call_gmail_api_directly():
    findings = _scan_brain_for_url_findings()
    bad = [
        f
        for f in findings
        if f.file_path == "brain/services/gmail_client.py"
        and f.host == "gmail.googleapis.com"
    ]
    assert not bad, f"gmail_client still calls gmail.googleapis.com: {bad}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TD: brain/routes/costs.py calls api.anthropic.com directly (admin "
        "usage/cost reports). Move behind Gateway /v1/cloud/anthropic_admin proxy."
    ),
)
def test_costs_does_not_call_anthropic_admin_directly():
    findings = _scan_brain_for_url_findings()
    bad = [
        f
        for f in findings
        if f.file_path == "brain/routes/costs.py" and f.host == "api.anthropic.com"
    ]
    assert not bad, f"costs.py still calls api.anthropic.com: {bad}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TD: brain/routes/costs.py calls cloudbilling.googleapis.com directly "
        "via subprocess curl (Google Cloud Billing). Move behind Gateway "
        "/v1/cloud/google_billing proxy."
    ),
)
def test_costs_does_not_call_google_billing_directly():
    findings = _scan_brain_for_url_findings()
    bad = [
        f
        for f in findings
        if f.file_path == "brain/routes/costs.py"
        and f.host == "cloudbilling.googleapis.com"
    ]
    assert not bad, f"costs.py still calls cloudbilling.googleapis.com: {bad}"


# -----------------------------------------------------------------------------
# Sanity tests: the scanner itself must work correctly.
# -----------------------------------------------------------------------------


def test_scanner_finds_at_least_known_violations():
    """Defense against a scanner bug that silently passes everything."""
    findings = _scan_brain_for_url_findings()
    found_hosts = {f.host for f in findings}
    expected = {h for (_, h) in KNOWN_VIOLATIONS}
    missing = expected - found_hosts
    assert not missing, (
        f"Scanner missed known-violation host(s) {missing} — scanner is broken "
        f"or KNOWN_VIOLATIONS is stale."
    )


def test_scanner_classifies_localhost_as_allowed():
    """Ensure 127.0.0.1 / localhost don't show up as findings."""
    findings = _scan_brain_for_url_findings()
    bad = [f for f in findings if f.host.lower() in {"127.0.0.1", "localhost"}]
    assert not bad, f"Scanner flagged localhost as violation: {bad}"


def test_scanner_classifies_tailscale_mesh_as_allowed():
    findings = _scan_brain_for_url_findings()
    bad = [f for f in findings if f.host.endswith(".tail40ed36.ts.net")]
    assert not bad, f"Scanner flagged Tailscale mesh as violation: {bad}"
