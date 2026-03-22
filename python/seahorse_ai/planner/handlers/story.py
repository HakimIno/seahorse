from __future__ import annotations

import logging
import time
from typing import Any

from seahorse_ai.planner.fast_utils import robust_json_load
from seahorse_ai.planner.handlers.base import BaseFastHandler
from seahorse_ai.planner.handlers.polars import PolarsHandler
from seahorse_ai.prompts.story import STORY_BOARDING_PROMPT, STORY_SYNTHESIS_PROMPT
from seahorse_ai.core.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)

class StoryHandler(BaseFastHandler):
    """Orchestrates professional data storytelling by combining multiple analysis steps."""

    def __init__(self, llm: Any, tools: Any):
        super().__init__(llm, tools)
        self._analyst = PolarsHandler(llm, tools)

    async def handle(self, prompt: str, history: list[Message] | None, start_t: float, **kwargs: Any) -> AgentResponse | None:
        try:
            # 1. Story Boarding
            boarding_msgs = [Message(role="user", content=STORY_BOARDING_PROMPT.format(prompt=prompt))]
            boarding_res = await self._llm.complete(boarding_msgs, tier="fast")
            content_str = str(boarding_res.get("content", boarding_res) if isinstance(boarding_res, dict) else boarding_res)
            plan = robust_json_load(content_str)
            
            if not plan or "steps" not in plan:
                logger.warning("StoryHandler: Failed to create a story plan.")
                return None

            story_results = []
            viz_tags = []

            # 2. Sequential Analysis
            for i, step in enumerate(plan["steps"]):
                purpose = step.get("purpose", "Analysis")
                query_focus = step.get("query_focus", prompt)
                
                logger.info(f"StoryHandler: Executing step {i+1}: {purpose}")
                
                # We use the analyst handler to perform individual steps
                res = await self._analyst.handle(query_focus, history, time.perf_counter())
                
                if res and res.content:
                    story_results.append(f"Step {i+1} ({purpose}):\n{res.content}")
                    # Extract viz tags
                    lines = res.content.splitlines()
                    for line in lines:
                        if line.startswith("ECHART_JSON:"):
                            viz_tags.append(line.strip())

            # 3. Narrative Synthesis
            synthesis_input = "\n\n".join(story_results)
            synth_msgs = [Message(role="user", content=STORY_SYNTHESIS_PROMPT.format(results=synthesis_input))]
            
            final_res = await self._llm.complete(synth_msgs, tier="worker")
            content = str(final_res.get("content", final_res) if isinstance(final_res, dict) else final_res)

            # Append all viz tags at the end
            viz_suffix = "\n\n".join(viz_tags)
            
            return AgentResponse(
                content=f"{content}\n\n{viz_suffix}",
                steps=len(plan["steps"]) + 2,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )

        except Exception as e:
            logger.error(f"StoryHandler: {e}")
            return None
