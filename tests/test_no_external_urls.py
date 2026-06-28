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
any whose host isn't in the allowlist or explicitly classified as non-egress.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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
    # honeypot fake .git/config response body
    ("brain/routes/honeypot.py", "github.com"),
    # honeypot fake debug API response body
    ("brain/routes/honeypot.py", "internal.fake.local"),
    # Microsoft Graph OAuth scope/audience identifiers; egress is via Gateway.
    ("brain/services/at0_mail_graph_client.py", "graph.microsoft.com"),
    ("brain/services/at0_mail_graph_client.py", "login.microsoftonline.com"),
    # Deterministic Beacon search-quality eval fixtures; no runtime egress.
    ("brain/services/internet_scout/search_quality_evals.py", "api.openai.com"),
    ("brain/services/internet_scout/search_quality_evals.py", "platform.openai.com"),
    # Static DOCX XML namespace identifier; not fetched over the network.
    ("brain/ingest/docx.py", "schemas.openxmlformats.org"),
    # Herald press pitch text; URL is emitted for human review, not fetched.
    ("brain/services/herald_press_outreach.py", "at-0.com"),
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
    known = set(KNOWN_NON_EGRESS)
    unknown = [f for f in findings if (f.file_path, f.host) not in known]
    assert not unknown, (
        "New public-internet URL(s) found in brain/ — Brain must route via Gateway. "
        "If a finding is genuinely not network egress (docstring, OAuth scope, "
        "honeypot response body), add it to KNOWN_NON_EGRESS. Otherwise route it "
        "through Gateway.\n"
        "Findings:\n"
        + "\n".join(
            f"  {f.file_path}:{f.line_number}  →  {f.host}  ({f.url_literal!r})"
            for f in unknown
        )
    )


# -----------------------------------------------------------------------------
# Sanity tests: the scanner itself must work correctly.
# -----------------------------------------------------------------------------


def test_scanner_finds_known_non_egress_literals():
    """Defense against a scanner bug that silently passes everything."""
    findings = _scan_brain_for_url_findings()
    found = {(f.file_path, f.host) for f in findings}
    expected = set(KNOWN_NON_EGRESS)
    missing = expected - found
    assert not missing, (
        f"Scanner missed known non-egress literal(s) {missing} — scanner is broken "
        f"or KNOWN_NON_EGRESS is stale."
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
