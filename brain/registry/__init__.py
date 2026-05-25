"""Skill and agent registry primitives."""

from brain.registry.catalog import INITIAL_AGENTS, INITIAL_SKILLS
from brain.registry.models import AgentSpec, SkillSpec

__all__ = ["AgentSpec", "SkillSpec", "INITIAL_AGENTS", "INITIAL_SKILLS"]
