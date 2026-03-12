import asyncio
import logging

from seahorse_ai.planner import ReActPlanner
from seahorse_ai.router import ModelRouter
from seahorse_ai.schemas import AgentRequest
from seahorse_ai.tools import make_default_registry

logging.basicConfig(level=logging.INFO)


async def test_intelligence() -> None:
    # Setup agent
    router = ModelRouter(
        worker_model="openrouter/inception/mercury-2",
        thinker_model="openrouter/openai/gpt-4o",
        strategist_model="openrouter/openai/gpt-4o",
    )
    registry = make_default_registry()
    planner = ReActPlanner(router, registry)

    # query that requires schema and memory
    prompt = "วิเคราะห์ยอดขายสินค้า Hero Product ของตารางปัจจุบันเปรียบเทียบกับแผนที่เราคุยกันเมื่อวานหน่อย"

    print("--- TESTING STRATEGIC INTELLIGENCE ---")
    print(f"Query: {prompt}")

    response = await planner.run(AgentRequest(prompt=prompt, agent_id="verification_test"))

    print(f"\nResponse Content:\n{response.content}")
    print(f"\nSteps taken: {response.steps}")


if __name__ == "__main__":
    asyncio.run(test_intelligence())
