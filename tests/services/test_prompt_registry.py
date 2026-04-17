"""Unit tests for prompt registry."""

import pytest

from brain.services.prompt_registry import (
    MarkdownRegistry,
    PromptNotFoundError,
)


@pytest.fixture
def temp_registry(tmp_path):
    (tmp_path / "planner_v1.md").write_text("PLANNER V1 CONTENT")
    (tmp_path / "planner_v2.md").write_text("PLANNER V2 CONTENT")
    (tmp_path / "reviewer_v1.md").write_text("REVIEWER V1")
    return MarkdownRegistry(root=tmp_path)


async def test_get_returns_file_contents(temp_registry):
    content = await temp_registry.get("planner", version="v1")
    assert content == "PLANNER V1 CONTENT"


async def test_get_different_versions(temp_registry):
    v1 = await temp_registry.get("planner", "v1")
    v2 = await temp_registry.get("planner", "v2")
    assert v1 != v2


async def test_get_missing_raises(temp_registry):
    with pytest.raises(PromptNotFoundError):
        await temp_registry.get("nonexistent", "v1")


async def test_list_versions(temp_registry):
    versions = await temp_registry.list_versions("planner")
    assert set(versions) == {"v1", "v2"}


async def test_list_versions_sorted_newest_first(temp_registry):
    versions = await temp_registry.list_versions("planner")
    assert versions[0] >= versions[-1]


async def test_list_versions_empty(temp_registry):
    versions = await temp_registry.list_versions("missing_prompt")
    assert versions == []


def test_missing_root_raises(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        MarkdownRegistry(root=tmp_path / "does_not_exist")
