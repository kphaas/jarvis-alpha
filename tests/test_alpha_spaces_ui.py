from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPACES_REGISTRY = REPO_ROOT / "ui" / "src" / "lib" / "spaces.ts"
LAYOUT = REPO_ROOT / "ui" / "src" / "components" / "Layout.tsx"
SPACE_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Space.tsx"


def test_alpha_spaces_registry_links_core_at0_domains() -> None:
    source = SPACES_REGISTRY.read_text(encoding="utf-8")

    for label in (
        "Family",
        "Financial",
        "Medical",
        "Legal",
        "Home",
        "Printer",
        "Forge",
        "Smithy",
        "Spark",
        "Privacy",
    ):
        assert f"label: '{label}'" in source

    for slug in (
        "family",
        "financial",
        "medical",
        "legal",
        "home",
        "printer",
        "forge",
        "smithy",
        "spark",
        "privacy",
    ):
        assert f"slug: '{slug}'" in source

    assert "aliases: ['familyvault']" in source
    assert "aliases: ['crucible', 'print-copilot']" in source
    assert "launchUrl:" in source
    assert "launchLabel:" in source
    assert "import.meta.env.VITE_ALPHA_UI_URL" in source
    assert "import.meta.env.VITE_FAMILY_UI_URL" in source
    assert "import.meta.env.VITE_FORGE_UI_URL" in source
    assert "alphaUrl('/spark')" in source
    assert "alphaUrl('/privacy')" in source


def test_layout_opens_space_launch_urls_from_shared_registry() -> None:
    source = LAYOUT.read_text(encoding="utf-8")

    assert "import { SPACES, getSpaceRoute } from '../lib/spaces'" in source
    assert "const SPACE_ITEMS = SPACES.map" in source
    assert "href: space.launchUrl" in source
    assert "to: getSpaceRoute(space)" in source
    assert "SPACE_ITEMS.map(item" in source
    assert 'target="_blank"' in source
    assert 'rel="noreferrer"' in source
    assert "handleSpaceClick(item.href)" in source
    assert "window.open(pendingSpaceHref, '_blank', 'noopener,noreferrer')" in source
    assert "Enter PIN to unlock all spaces" in source


def test_space_page_uses_registry_launch_urls_for_domain_links() -> None:
    source = SPACE_PAGE.read_text(encoding="utf-8")

    assert "import { SPACES, getSpaceBySlug } from '../lib/spaces'" in source
    assert "const space = getSpaceBySlug(slug)" in source
    assert "SPACES.map(item" in source
    assert "href={item.launchUrl}" in source
    assert 'target="_blank"' in source
    assert 'rel="noreferrer"' in source
    assert "Domain links" in source
    assert "{SPACES.length} spaces" in source
