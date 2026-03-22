from __future__ import annotations

import logging
from typing import Any

import msgspec

logger = logging.getLogger(__name__)


class SeahorseSkill(msgspec.Struct):
    """A collection of tools and prompt rules that define a specific agent capability."""

    name: str
    description: str
    rules: list[str]
    tools: list[Any]  # Functions decorated with @tool

    def get_prompt_snippet(self) -> str:
        """Return the formatted prompt rules for this skill."""
        if not self.rules:
            return ""

        snippet = f"### Skill: {self.name}\n"
        for i, rule in enumerate(self.rules, 1):
            snippet += f"{i}. {rule}\n"
        return snippet


class SkillRegistry:
    """A registry for managing and discovering SeahorseSkills."""

    def __init__(self) -> None:
        self._skills: dict[str, SeahorseSkill] = {}

    def register(self, skill: SeahorseSkill) -> None:
        self._skills[skill.name.upper()] = skill
        logger.info("Registered skill: %s", skill.name)

    def get(self, name: str) -> SeahorseSkill | None:
        return self._skills.get(name.upper())

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())

    def get_all_tools(self) -> list[Any]:
        """Collect and deduplicate all tools from all registered skills."""
        all_tools = []
        seen_names = set()
        for skill in self._skills.values():
            for tool in skill.tools:
                # Assuming tools have a __name__ attribute
                name = getattr(tool, "__name__", str(tool))
                if name not in seen_names:
                    all_tools.append(tool)
                    seen_names.add(name)
        return all_tools


# Global registry instance
registry = SkillRegistry()
