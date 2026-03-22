"""Base SeahorseTeam for YAML-driven multi-agent systems."""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

import yaml

from seahorse_ai.engines.swarm import CrewAgent, SeahorseTask
from seahorse_ai.planner import LLMBackend, ReActPlanner
from seahorse_ai.skills.base import registry as skill_registry
from seahorse_ai.tools import make_default_registry
from seahorse_ai.tools.base import SeahorseToolRegistry

logger = logging.getLogger(__name__)


@runtime_checkable
class SeahorseTeamProtocol(Protocol):
    name: str

    async def get_agents_and_tasks(
        self, objective: str, llm: LLMBackend
    ) -> tuple[list[CrewAgent], list[SeahorseTask]]: ...


class TeamRegistry:
    def __init__(self) -> None:
        self._teams: dict[str, SeahorseTeamProtocol] = {}

    def register(self, team: SeahorseTeamProtocol) -> None:
        self._teams[team.name.upper()] = team
        logger.info(f"TeamRegistry: Registered team '{team.name}'")

    def get(self, name: str) -> SeahorseTeamProtocol | None:
        return self._teams.get(name.upper())

    def list_teams(self) -> list[str]:
        return list(self._teams.keys())


# Global registry instance
registry = TeamRegistry()


class SeahorseTeam:
    """Base class for all agent teams. Supports loading from YAML configs."""

    name: str = "BASE"
    config_dir: str = ""

    async def get_agents_and_tasks(
        self, objective: str, llm: LLMBackend, inputs: dict[str, Any] | None = None
    ) -> tuple[list[CrewAgent], list[SeahorseTask]]:
        if not self.config_dir:
            base_path = os.path.dirname(os.path.abspath(__file__))
            self.config_dir = os.path.join(base_path, "config", self.name.lower())

        inputs = inputs or {}
        if "objective" not in inputs:
            inputs["objective"] = objective

        agents_config = self._load_yaml("agents.yaml")
        tasks_config = self._load_yaml("tasks.yaml")

        agents_map = {}
        for agent_key, cfg in agents_config.items():
            role = cfg["role"].format(**inputs)
            goal = cfg["goal"].format(**inputs)
            backstory = cfg["backstory"].format(**inputs)

            skills = []
            tools_registry = SeahorseToolRegistry()
            skill_names = cfg.get("skills", [])
            for s_name in skill_names:
                skill = skill_registry.get(s_name)
                if skill:
                    skills.append(skill)
                    for t in skill.tools:
                        tools_registry.register(t)

            if not skills:
                tools_registry = make_default_registry()

            agent_identity = (
                f"\n\n## Your Identity\nRole: {role}\nGoal: {goal}\nBackstory: {backstory}\n"
            )
            agent_tier = cfg.get(
                "tier", self._default_tier if hasattr(self, "_default_tier") else "worker"
            )
            planner = ReActPlanner(
                llm=llm,
                tools=tools_registry,
                skills=skills,
                identity_prompt=agent_identity,
                step_timeout_seconds=120,
                default_tier=agent_tier,
            )

            agent = CrewAgent(
                name=agent_key.capitalize(),
                role=role,
                goal=goal,
                backstory=backstory,
                planner=planner,
                skills=skills,
            )
            agents_map[agent_key] = agent

        tasks = []
        for _task_key, cfg in tasks_config.items():
            desc = cfg["description"].format(**inputs)
            expected = cfg["expected_output"].format(**inputs)
            agent_key = cfg["agent"]

            task = SeahorseTask(
                description=desc, expected_output=expected, agent_name=agents_map[agent_key].name
            )
            tasks.append(task)

        return list(agents_map.values()), tasks

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        path = os.path.join(self.config_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path) as f:
            return yaml.safe_load(f)
