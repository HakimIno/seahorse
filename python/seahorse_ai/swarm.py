"""seahorse_ai.swarm — Multi-agent orchestration (Swarm).

Allows defining specialized agents that can delegate tasks to each other via a shared
ToolRegistry and Message Bus.

Fixed issues (Phase 2):
- Closure bug: delegate_tool now captures name/planner by value via default args
- Master planner is now cached and not re-created on every request
"""
from __future__ import annotations

import asyncio
import logging

from seahorse_ai.planner import LLMBackend, ReActPlanner, ToolRegistry
from seahorse_ai.schemas import AgentRequest
from seahorse_ai.tools.base import SeahorseToolRegistry, tool

logger = logging.getLogger(__name__)


class SwarmAgent:
    """A member of a Swarm that can be delegated to."""

    def __init__(self, name: str, description: str, planner: ReActPlanner) -> None:
        self.name = name
        self.description = description
        self.planner = planner


class SwarmOrchestrator:
    """Manages a collection of agents and provides a unified entry point."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm
        self._agents: dict[str, SwarmAgent] = {}
        self._shared_registry = SeahorseToolRegistry()
        self._master: ReActPlanner | None = None  # Cached — not re-created per request

    def add_agent(self, name: str, description: str, tools: ToolRegistry) -> None:
        """Register a new specialized agent in the swarm."""
        planner = ReActPlanner(llm=self._llm, tools=tools)
        agent = SwarmAgent(name, description, planner)
        self._agents[name] = agent

        # FIX: Capture name and planner by value using default args.
        # Without this, all closures would share the same (last) loop variables.
        @tool(f"Delegate complex {name} tasks to this specialized agent. Useful for: {description}")
        async def delegate_tool(query: str, _name: str = name, _planner: ReActPlanner = planner) -> str:
            logger.info("Swarm: delegating to %s", _name)
            request = AgentRequest(prompt=query, agent_id=f"swarm_{_name}")
            response = await _planner.run(request)
            return response.content

        self._shared_registry.register(delegate_tool)
        # Invalidate cached master so it picks up the new tool
        self._master = None
        logger.info("Swarm: added agent '%s'", name)

    async def run(self, prompt: str) -> str:
        """Run the main 'Master' agent which routes to specialists.

        The master planner is cached and reused across requests.
        It is invalidated whenever a new agent is added.
        """
        if self._master is None:
            self._master = ReActPlanner(llm=self._llm, tools=self._shared_registry)
            logger.info("Swarm: master planner created (agents=%d)", len(self._agents))

        request = AgentRequest(prompt=prompt)
        response = await self._master.run(request)
        return response.content

    async def broadcast(self, prompt: str) -> dict[str, str]:
        """Send the same prompt to ALL agents in parallel and gather responses.

        Useful for Tier 3 'Cognitive Synthesis' where different perspectives are needed.
        """
        logger.info("Swarm: broadcasting prompt to %d agents", len(self._agents))

        agent_names = list(self._agents.keys())
        tasks = [
            self._agents[name].planner.run(AgentRequest(prompt=prompt))
            for name in agent_names
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            name: (res.content if not isinstance(res, Exception) else f"Error: {res}")
            for name, res in zip(agent_names, results, strict=False)
        }

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())
