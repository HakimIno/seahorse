import asyncio
import logging
import sys
import os
import json

# Add python dir to path
sys.path.append(os.path.join(os.getcwd(), "python"))

from seahorse_ai.planner import ReActPlanner
from seahorse_ai.schemas import Message

logging.basicConfig(level=logging.INFO)

class MockLLM:
    async def complete(self, messages, tools=None):
        content = messages[-1].content
        if "PROACTIVE" in content:
            return '{"suggestion": "Analyze OpenClaw vulnerabilities", "reason": "User is browsing a security-related repo", "priority": 5}'
        return "Standard response"

class MockTools:
    async def call(self, name, args):
        return "Mock result"
    def to_openai_tools(self):
        return []

async def test_proactive():
    print("🚀 Starting Proactive Brain Verification...")
    planner = ReActPlanner(llm=MockLLM(), tools=MockTools())
    
    # Wait for ghost node to start
    await asyncio.sleep(2)
    print(f"👻 Peer ID: {planner._ghost.get_peer_id()}")
    
    # Simulate a context change
    print("🎯 Simulating context change...")
    # Wait for reasoning
    await asyncio.sleep(5)
    
    # Simulate a user clicking "EXECUTE" in the UI
    print("🖱️ Simulating UI click: 'EXECUTE' for CODE_REVIEW")
    cmd_json = json.dumps({"action_id": "CODE_REVIEW", "suggestion": "Review this new Rust file"})
    planner._ghost.send_command(cmd_json)
    
    # Wait for command detection
    await asyncio.sleep(5)
    
    print("✅ Verification complete. Check logs for 'RECEIVED COMMAND' and tool execution.")

if __name__ == "__main__":
    asyncio.run(test_proactive())
