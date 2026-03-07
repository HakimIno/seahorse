"""seahorse_ai.swarm — Multi-agent orchestration (Swarm).

Allows defining specialized agents that can delegate tasks to each other via a shared
ToolRegistry and Message Bus.
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

    async def broadcast(self, prompt: str) -> dict[str, str]:
        """Send the same prompt to ALL agents in parallel and gather responses.
        
        Useful for Tier 3 'Cognitive Synthesis' where different perspectives are needed.
        """
        logger.info("Swarm: broadcasting prompt to %d agents", len(self._agents))
        
        tasks = []
        agent_names = list(self._agents.keys())
        
        for name in agent_names:
            agent = self._agents[name]
            request = AgentRequest(prompt=prompt)
            tasks.append(agent.planner.run(request))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = {}
        for name, res in zip(agent_names, results, strict=False):
            if isinstance(res, Exception):
                logger.error("Swarm: agent '%s' failed: %s", name, res)
                final_results[name] = f"Error: {res}"
            else:
                final_results[name] = res.content
                
        return final_results

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())
