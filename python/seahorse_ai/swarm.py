"""seahorse_ai.swarm — Multi-agent orchestration (Swarm).

Allows defining specialized agents that can delegate tasks to each other via a shared
ToolRegistry and Message Bus.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from seahorse_ai.planner import LLMBackend, ReActPlanner, ToolRegistry
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message
from seahorse_ai.tools.base import SeahorseToolRegistry, tool

logger = logging.getLogger(__name__)

class SwarmAgent:
    """A member of a Swarm that can be delegated to."""
    
    def __init__(self, name: str, description: str, planner: ReActPlanner):
        self.name = name
        self.description = description
        self.planner = planner

class SwarmOrchestrator:
    """Manages a collection of agents and provides a unified entry point."""
    
    def __init__(self, llm: LLMBackend):
        self._llm = llm
        self._agents: Dict[str, SwarmAgent] = {}
        self._shared_registry = SeahorseToolRegistry()
        
    def add_agent(self, name: str, description: str, tools: ToolRegistry) -> None:
        """Register a new specialized agent in the swarm."""
        planner = ReActPlanner(llm=self._llm, tools=tools)
        agent = SwarmAgent(name, description, planner)
        self._agents[name] = agent
        
        # Define a delegation tool for this specific agent
        @tool(f"Delegate complex {name} tasks to this specialized agent. Useful for: {description}")
        async def delegate_tool(query: str) -> str:
            logger.info("Swarm: delegating to %s", name)
            request = AgentRequest(prompt=query)
            response = await planner.run(request)
            return response.content

        self._shared_registry.register(delegate_tool)
        logger.info("Swarm: added agent '%s'", name)

    async def run(self, prompt: str) -> str:
        """Run the main 'Master' agent which routes to specialists."""
        # The Master agent has access to all delegation tools
        master = ReActPlanner(llm=self._llm, tools=self._shared_registry)
        request = AgentRequest(prompt=prompt)
        response = await master.run(request)
        return response.content

    @property
    def agent_names(self) -> List[str]:
        return list(self._agents.keys())
