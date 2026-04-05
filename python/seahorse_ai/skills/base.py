from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import msgspec

logger = logging.getLogger(__name__)


class SeahorseSkill(msgspec.Struct):
    """A collection of tools and prompt rules that define a specific agent capability."""

    name: str
    description: str
    rules: list[str]
    tools: list[Any] = []  # Resolved function objects
    tool_names: list[str] = []  # Names of tools if loaded from disk

    def get_prompt_snippet(self) -> str:
        """Return the formatted prompt rules for this skill."""
        if not self.rules:
            return ""

        snippet = f"### Skill: {self.name}\n"
        for i, rule in enumerate(self.rules, 1):
            snippet += f"{i}. {rule}\n"
        return snippet

    @classmethod
    def from_markdown(cls, content: str) -> SeahorseSkill:
        """Parse a skill from a Markdown string with JSON metadata block.

        Example Format:
        ```json
        {
          "name": "TRADING_GUARDIAN",
          "description": "Risk management and portfolio tracking.",
          "tools": ["calculate_position_size", "get_ibkr_account_summary"]
        }
        ```
        # Rules
        - Rule 1
        - Rule 2
        """
        # Extract JSON block
        json_match = re.search(r"```json\s+(.*?)\s+```", content, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON metadata block found in skill markdown")

        meta = json.loads(json_match.group(1))

        # Extract Rules (lines starting with - or * or numbers after # Rules)
        rules = []
        rules_match = re.search(r"#+ Rules\s+(.*)", content, re.DOTALL | re.IGNORECASE)
        if rules_match:
            lines = rules_match.group(1).strip().split("\n")
            for line in lines:
                clean = line.strip().lstrip("-*0123456789. ").strip()
                if clean:
                    rules.append(clean)

        return cls(
            name=meta["name"],
            description=meta["description"],
            rules=rules,
            tool_names=meta.get("tools", []),
            tools=[],
        )


class SkillRegistry:
    """A registry for managing and discovering SeahorseSkills."""

    def __init__(self) -> None:
        self._skills: dict[str, SeahorseSkill] = {}

    def register(self, skill: SeahorseSkill) -> None:
        self._skills[skill.name.upper()] = skill
        logger.info("Registered skill: %s", skill.name)

    def load_plugins(self, directory: str) -> None:
        """Scan a directory for .md skill manifests and load them."""
        if not os.path.exists(directory):
            logger.warning("Plugin directory not found: %s", directory)
            return

        for filename in os.listdir(directory):
            if filename.endswith(".md"):
                path = os.path.join(directory, filename)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                    skill = SeahorseSkill.from_markdown(content)
                    self.register(skill)
                except Exception as e:
                    logger.error("Failed to load skill plugin %s: %s", filename, e)

    def resolve_tools(self, tool_registry: Any) -> None:
        """Resolve tool_names into actual function objects using a tool registry."""
        for skill in self._skills.values():
            if not skill.tool_names:
                continue

            resolved = []
            for name in skill.tool_names:
                tool_fn = tool_registry.get(name)
                if tool_fn:
                    resolved.append(tool_fn)
                else:
                    logger.warning("Skill %s: tool '%s' not found in registry", skill.name, name)
            skill.tools = resolved

    async def find_best_match(self, prompt: str, llm: Any) -> SeahorseSkill | None:
        """Use the LLM to pick the best skill based on context (Semantic Matching)."""
        if not self._skills:
            return None

        skills_list = [
            {"name": s.name, "description": s.description} for s in self._skills.values()
        ]

        # Use a very fast prompt for routing
        system_msg = (
            "You are Seahorse Intent Router. Given a user prompt and a list of skills, "
            "return only the NAME of the best matching skill. If none match, return 'NONE'.\n"
            f"Available Skills: {skills_list}"
        )

        from seahorse_ai.core.schemas import Message

        messages = [
            Message(role="system", content=system_msg),
            Message(role="user", content=f"Prompt: {prompt}"),
        ]

        try:
            # Use 'fast' tier if possible
            resp = await llm.complete(messages, tier="fast")
            best_name = str(resp.get("content", resp)).strip().upper()

            if best_name == "NONE" or best_name not in self._skills:
                return None

            return self._skills[best_name]
        except Exception as e:
            logger.error("Skill semantic matching failed: %s", e)
            return None

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
                name = getattr(tool, "__name__", str(tool))
                if name not in seen_names:
                    all_tools.append(tool)
                    seen_names.add(name)
        return all_tools


# Global registry instance
registry = SkillRegistry()
