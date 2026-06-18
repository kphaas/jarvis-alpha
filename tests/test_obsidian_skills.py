from decimal import Decimal

import pytest

from brain.skills.obsidian import (
    ObsidianSkillError,
    notes_search,
    notes_write_private_digest,
    tasks_create,
)
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall


def _call(
    skill_name: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
) -> SkillCall:
    invocation = SkillInvocation(
        agent_id="dream_mode",
        skill_name=skill_name,
        idempotency_key=idempotency_key,
    )
    decision = SkillPolicyDecision(
        outcome="allow",
        reason="policy_ok",
        agent_id="dream_mode",
        skill_name=skill_name,
        approval_tier="T1",
        skill_scope="notes.read",
        estimated_cost_usd=Decimal("0"),
    )
    return SkillCall(invocation=invocation, decision=decision, payload=payload)


@pytest.mark.asyncio
async def test_notes_search_returns_ranked_vault_matches(tmp_path):
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Alpha.md").write_text(
        "# Alpha\nDream mode can create Obsidian tasks.\n",
        encoding="utf-8",
    )
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "workspace.md").write_text(
        "Dream mode hidden config should not appear.\n",
        encoding="utf-8",
    )

    result = await notes_search(
        _call(
            "notes.search",
            {
                "_vault_root": str(tmp_path),
                "query": "dream mode",
                "max_results": 5,
            },
        )
    )

    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["results"][0]["path"] == "Projects/Alpha.md"
    assert "Dream mode" in result["results"][0]["excerpt"]


@pytest.mark.asyncio
async def test_notes_write_private_digest_creates_idempotent_searchable_note(tmp_path):
    first = await notes_write_private_digest(
        _call(
            "notes.write_private_digest",
            {
                "_vault_root": str(tmp_path),
                "title": "Ken Resume Digest",
                "body": "Private Alpha vault summary for a Staff Platform role.",
                "tags": ["career/private", "#talent-ops"],
                "document_id": "doc-123",
                "source_name": "Ken Resume.pdf",
            },
            idempotency_key="resume-digest-1",
        )
    )
    second = await notes_write_private_digest(
        _call(
            "notes.write_private_digest",
            {
                "_vault_root": str(tmp_path),
                "title": "Ken Resume Digest",
                "body": "Private Alpha vault summary for a Staff Platform role.",
            },
            idempotency_key="resume-digest-1",
        )
    )

    note_path = tmp_path / "AT-0" / "Private Document Digests" / "ken-resume-digest.md"
    content = note_path.read_text(encoding="utf-8")
    search = await notes_search(
        _call(
            "notes.search",
            {
                "_vault_root": str(tmp_path),
                "query": "Staff Platform",
                "max_results": 5,
            },
        )
    )

    assert first["status"] == "created"
    assert first["path"] == "AT-0/Private Document Digests/ken-resume-digest.md"
    assert second["status"] == "exists"
    assert content.count("jarvis-note-id:resume-digest-1") == 1
    assert "private: true" in content
    assert 'source: "alpha-vault-digest"' in content
    assert 'document_id: "doc-123"' in content
    assert "Private Alpha vault summary" in content
    assert search["count"] == 1
    assert search["results"][0]["path"] == first["path"]


@pytest.mark.asyncio
async def test_notes_write_private_digest_refuses_to_clobber_existing_note(tmp_path):
    target_dir = tmp_path / "AT-0" / "Private Document Digests"
    target_dir.mkdir(parents=True)
    (target_dir / "ken-resume-digest.md").write_text(
        "# Handwritten note\nDo not overwrite me.\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ObsidianSkillError,
        match="target_exists_without_digest_marker",
    ):
        await notes_write_private_digest(
            _call(
                "notes.write_private_digest",
                {
                    "_vault_root": str(tmp_path),
                    "title": "Ken Resume Digest",
                    "body": "Generated digest.",
                },
                idempotency_key="resume-digest-2",
            )
        )


@pytest.mark.asyncio
async def test_tasks_create_appends_markdown_task_idempotently(tmp_path):
    first = await tasks_create(
        _call(
            "tasks.create",
            {
                "_vault_root": str(tmp_path),
                "title": "Review Dream soak",
                "due": "2026-05-27",
                "tags": ["project/jarvis-alpha", "#ops"],
            },
            idempotency_key="dream-16-review",
        )
    )
    second = await tasks_create(
        _call(
            "tasks.create",
            {
                "_vault_root": str(tmp_path),
                "title": "Review Dream soak",
                "due": "2026-05-27",
                "tags": ["project/jarvis-alpha", "#ops"],
            },
            idempotency_key="dream-16-review",
        )
    )

    inbox = tmp_path / "Inbox.md"
    content = inbox.read_text(encoding="utf-8")

    assert first["status"] == "created"
    assert first["path"] == "Inbox.md"
    assert second["status"] == "exists"
    assert content.count("jarvis-task-id:dream-16-review") == 1
    assert "Review Dream soak" in content
    assert "2026-05-27" in content
    assert "#ops" in content
    assert "#project/jarvis-alpha" in content


@pytest.mark.asyncio
async def test_tasks_create_requires_idempotency_key(tmp_path):
    with pytest.raises(ObsidianSkillError, match="valid_idempotency_key_required"):
        await tasks_create(
            _call(
                "tasks.create",
                {
                    "_vault_root": str(tmp_path),
                    "title": "Unsafe duplicate-prone task",
                },
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "key_suffix"),
    [
        ("../Inbox.md", "traversal"),
        ("/tmp/Inbox.md", "absolute"),
        (".secret/Inbox.md", "hidden"),
        ("Inbox.txt", "nonmarkdown"),
    ],
)
async def test_tasks_create_rejects_unsafe_paths(tmp_path, path, key_suffix):
    with pytest.raises((ObsidianSkillError, ValueError)):
        await tasks_create(
            _call(
                "tasks.create",
                {
                    "_vault_root": str(tmp_path),
                    "title": "Should not write",
                    "path": path,
                },
                idempotency_key=f"unsafe-{key_suffix}",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "key_suffix"),
    [
        ("../Digest.md", "traversal"),
        ("/tmp/Digest.md", "absolute"),
        (".secret/Digest.md", "hidden"),
        ("Digest.txt", "nonmarkdown"),
    ],
)
async def test_notes_write_private_digest_rejects_unsafe_paths(
    tmp_path,
    path,
    key_suffix,
):
    with pytest.raises((ObsidianSkillError, ValueError)):
        await notes_write_private_digest(
            _call(
                "notes.write_private_digest",
                {
                    "_vault_root": str(tmp_path),
                    "title": "Unsafe digest",
                    "body": "Should not write.",
                    "path": path,
                },
                idempotency_key=f"unsafe-digest-{key_suffix}",
            )
        )
