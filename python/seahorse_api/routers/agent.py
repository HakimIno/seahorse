"""Agent routes — /v1/agent/run and /v1/agent/stream."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from seahorse_ai.llm import LLMClient
from seahorse_ai.planner import ReActPlanner
from seahorse_ai.schemas import AgentRequest, AgentResponse, LLMConfig
from seahorse_ai.tools import SeahorseToolRegistry

router = APIRouter()


@lru_cache(maxsize=1)
def _get_tool_registry() -> SeahorseToolRegistry:
    from seahorse_ai.tools import make_default_registry
    return make_default_registry()


@lru_cache(maxsize=1)
def _get_planner() -> ReActPlanner:
    llm = LLMClient(config=LLMConfig())
    return ReActPlanner(llm=llm, tools=_get_tool_registry())


def get_planner() -> ReActPlanner:
    return _get_planner()


@router.post("/run", response_model=AgentResponse)
async def run_agent(
    request: AgentRequest,
    planner: ReActPlanner = Depends(get_planner),
) -> AgentResponse:
    """Run the agent synchronously and return the final response."""
    return await planner.run(request)


@router.post("/stream")
async def stream_agent(
    request: AgentRequest,
    planner: ReActPlanner = Depends(get_planner),
) -> StreamingResponse:
    """Stream agent tokens via SSE."""

    async def _token_stream() -> object:
        async for token in planner._llm.stream(  # noqa: SLF001
            [
                __import__("seahorse_ai.schemas", fromlist=["Message"]).Message(
                    role="user", content=request.prompt
                )
            ]
        ):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_token_stream(), media_type="text/event-stream")
