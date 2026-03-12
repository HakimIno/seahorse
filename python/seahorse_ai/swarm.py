"""seahorse_ai.swarm — Multi-agent orchestration (Swarm).

Allows defining specialized agents that can delegate tasks to each other via a shared
ToolRegistry and Message Bus.

Fixed issues (Phase 2):
- Closure bug: delegate_tool now captures name/planner by value via default args
- Master planner is now cached and not re-created on every request
"""

from __future__ import annotations

import logging
from typing import Any

import anyio

from seahorse_ai.planner import LLMBackend, ReActPlanner, ToolRegistry
from seahorse_ai.schemas import AgentRequest
from seahorse_ai.skills.base import SeahorseSkill
from seahorse_ai.tools.base import SeahorseToolRegistry, tool

logger = logging.getLogger(__name__)


class SwarmAgent:
    """A member of a Swarm that can be delegated to."""

    def __init__(self, name: str, description: str, planner: ReActPlanner) -> None:
        self.name = name
        self.description = description
        self.planner = planner


class CrewAgent(SwarmAgent):
    """A specialized agent with a role, goal, and backstory (CrewAI-inspired)."""

    def __init__(
        self,
        name: str,
        role: str,
        goal: str,
        backstory: str,
        planner: ReActPlanner,
        skills: list[SeahorseSkill] | None = None,
    ) -> None:
        super().__init__(name, description=f"{role}: {goal}", planner=planner)
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self.skills = skills or []

    def build_system_prompt_extension(self) -> str:
        """Inject Role/Goal/Backstory into the system prompt."""
        return (
            f"\n\n## Your Identity\n"
            f"Role: {self.role}\n"
            f"Goal: {self.goal}\n"
            f"Backstory: {self.backstory}\n"
        )


class SeahorseTask:
    """A specific objective assigned to an agent."""

    def __init__(
        self,
        description: str,
        expected_output: str,
        agent_name: str,
        context_from_tasks: list[str] | None = None,
    ) -> None:
        self.description = description
        self.expected_output = expected_output
        self.agent_name = agent_name
        self.context_from_tasks = context_from_tasks or []
        self.output: str | None = None


class SeahorseCrew:
    """Orchestrates a list of tasks performed by a team of CrewAgents."""

    def __init__(self, agents: list[CrewAgent], tasks: list[SeahorseTask]) -> None:
        self.agents = {a.name: a for a in agents}
        self.tasks = tasks

    async def kickoff(self) -> dict[str, Any]:
        """Execute all tasks in sequence, passing context between them."""
        overall_context = ""
        last_output = ""
        all_image_paths = []

        for i, task in enumerate(self.tasks):
            agent = self.agents.get(task.agent_name)
            if not agent:
                logger.error("Crew: Agent '%s' not found for task %d", task.agent_name, i)
                continue

            # Build specialized prompt for this task
            context_snippet = (
                f"\n\nContext from previous steps:\n{overall_context}" if overall_context else ""
            )

            task_prompt = (
                f"TASK DESCRIPTION: {task.description}\n"
                f"EXPECTED OUTPUT: {task.expected_output}\n"
                f"{context_snippet}"
            )

            logger.info("Crew: Agent '%s' starting task: %s", agent.name, task.description[:50])

            # Temporary override of system prompt via history injection if needed
            # For now, we rely on the agent's planner already being configured
            request = AgentRequest(
                prompt=task_prompt,
                agent_id=f"crew_{agent.name}_task_{i}",
            )

            response = await agent.planner.run(request)
            last_output = response.content
            task.output = last_output

            # Collect image paths
            if response.image_paths:
                all_image_paths.extend(response.image_paths)

            # Accumulate context (with truncation to avoid token bloat)
            overall_context += f"\n--- Result of Task {i} ({agent.role}) ---\n{last_output}\n"

            # Simple truncation: Keep only the last ~4000 chars of context
            if len(overall_context) > 4000:
                overall_context = "..." + overall_context[-4000:]

        return {"content": last_output, "image_paths": all_image_paths if all_image_paths else None}


class SwarmOrchestrator:
    """Manages a collection of agents communicating asynchronously via Rust MessageBus."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm
        self._agents: dict[str, CrewAgent] = {}
        self._shared_registry = SeahorseToolRegistry()
        self._master: ReActPlanner | None = None

        # Initialize Rust PyMessageBus
        try:
            from seahorse_ffi import PyMessageBus

            self._bus = PyMessageBus(1024)
            logger.info("SwarmOrchestrator: Rust PyMessageBus initialized.")
        except ImportError:
            logger.warning(
                "SwarmOrchestrator: PyMessageBus not found. Run `uv run maturin develop`. Falling back to dummy."
            )
            self._bus = None

    def add_agent(
        self,
        name: str,
        role: str,
        goal: str,
        backstory: str,
        tools: ToolRegistry,
    ) -> None:
        """Register a new specialized CrewAgent equipped with real-time Pub/Sub tools."""
        agent_identity = (
            f"\n\n## Your Identity\n"
            f"Role: {role}\n"
            f"Goal: {goal}\n"
            f"Backstory: {backstory}\n"
            f"\n## Communication Directive\n"
            f"You are part of a real-time multi-agent swarm. Do NOT wait for blocking responses. "
            f"Use `send_message` to communicate directly with other agents or `broadcast` for general alerts.\n"
        )

        # Merge specific tools with communication tools
        agent_tools = SeahorseToolRegistry()
        for fn, _ in tools._tools.values():
            agent_tools.register(fn)

        @tool(
            f"Send a direct message to a specific agent in the swarm. Available: {list(self._agents.keys())}"
        )
        async def send_message(recipient: str, message: str) -> str:
            if not self._bus:
                return "Message failed: Bus offline."
            self._bus.publish(f"agent_{recipient.lower()}", name, message)
            logger.info("Swarm: %s sent message to %s", name, recipient)
            return f"Message queued to {recipient}."

        @tool(
            "Broadcast a general message to all agents listening to a specific topic (e.g., 'system', 'data')."
        )
        async def broadcast(topic: str, message: str) -> str:
            if not self._bus:
                return "Broadcast failed: Bus offline."
            self._bus.publish(topic, name, message)
            logger.info("Swarm: %s broadcasted to topic '%s'", name, topic)
            return f"Broadcasted to {topic}."

        agent_tools.register(send_message)
        agent_tools.register(broadcast)

        planner = ReActPlanner(llm=self._llm, tools=agent_tools, identity_prompt=agent_identity)
        agent = CrewAgent(name, role, goal, backstory, planner)
        self._agents[name] = agent
        self._master = None
        logger.info("Swarm: added agent '%s' as %s", name, role)

    async def _run_agent_listener(self, agent: CrewAgent):
        """Background task for an agent to listen for direct messages on the Bus."""
        if not self._bus:
            return

        topic = f"agent_{agent.name.lower()}"
        receiver = self._bus.subscribe(topic)
        logger.info("Swarm: %s listening on topic '%s'", agent.name, topic)

        async with anyio.create_task_group() as tg:
            while True:
                try:
                    msg = await anyio.to_thread.run_sync(receiver.recv)

                    if msg is not None:
                        logger.info(
                            "Swarm [%s] INBOX: from %s -> %s", agent.name, msg["sender"], msg["content"]
                        )

                        # Context injection for real-time reactivity
                        inbound_prompt = f"INBOUND MESSAGE from {msg['sender']}:\n{msg['content']}\nPlease acknowledge or act on this."
                        request = AgentRequest(prompt=inbound_prompt, agent_id=f"crew_{agent.name}_rx")

                        # Start reagent task in group
                        tg.start_soon(agent.planner.run, request)

                except Exception as e:
                    # Ignore common Rust bridge timeouts
                    if "timeout" not in str(e).lower() and "panic" not in str(e).lower():
                        logger.error("Swarm [%s] listener trapped: %s", agent.name, e)

    async def run(self, prompt: str) -> str:
        """Run the swarm asynchronously using AnyIO TaskGroup."""
        if self._master is None:
            self._master = ReActPlanner(llm=self._llm, tools=self._shared_registry)

        async with anyio.create_task_group() as tg:
            # Start listeners for all agents in the task group
            for agent in self._agents.values():
                tg.start_soon(self._run_agent_listener, agent)

            # Use msgspec-ready AgentRequest
            request = AgentRequest(prompt=prompt)
            response = await self._master.run(request)

            # Signal task group to shut down
            tg.cancel_scope.cancel()

        return response.content
