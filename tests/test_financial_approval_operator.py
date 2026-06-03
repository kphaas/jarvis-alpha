from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_operator() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "financial_approval_operator.py"
    )
    spec = importlib.util.spec_from_file_location("financial_approval_operator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load financial_approval_operator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


operator = _load_operator()


def test_base_url_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_ALPHA_BASE_URL", "https://alpha.test/")

    assert operator._base_url(None) == "https://alpha.test"


def test_is_financial_paper_requires_actor_and_actions() -> None:
    assert operator._is_financial_paper(
        {
            "actor_sub": "jarvis-fin-agent",
            "action_class": ["financial_trade", "paper_trade"],
        }
    )
    assert not operator._is_financial_paper(
        {
            "actor_sub": "other",
            "action_class": ["financial_trade", "paper_trade"],
        }
    )
    assert not operator._is_financial_paper(
        {
            "actor_sub": "jarvis-fin-agent",
            "action_class": ["financial_trade"],
        }
    )


def test_select_pending_by_explicit_approval_id() -> None:
    item = {"id": "approval-1", "actor_sub": "other", "action_class": []}

    assert (
        operator._select_pending(
            [item],
            approval_id="approval-1",
            latest_financial_paper=False,
        )
        is item
    )


def test_select_pending_latest_financial_paper_uses_latest_match() -> None:
    first = {
        "id": "first",
        "actor_sub": "jarvis-fin-agent",
        "action_class": ["financial_trade", "paper_trade"],
    }
    second = {
        "id": "second",
        "actor_sub": "jarvis-fin-agent",
        "action_class": ["paper_trade", "financial_trade"],
    }

    assert (
        operator._select_pending(
            [first, {"id": "ignore"}, second],
            approval_id=None,
            latest_financial_paper=True,
        )
        is second
    )


def test_select_pending_requires_selector() -> None:
    with pytest.raises(RuntimeError, match="pass --approval-id"):
        operator._select_pending([], approval_id=None, latest_financial_paper=False)
