"""seahorse_ai.adapters.discord_adapter — Discord bot adapter for Seahorse.

This adapter allows Seahorse to run as a Discord bot, listening for messages
and responding using the ReActPlanner.

Usage:
    export DISCORD_BOT_TOKEN=your_token
    uv run python -m seahorse_ai.adapters.discord_adapter
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from seahorse_ai.planner import ReActPlanner
from seahorse_ai.router import ModelRouter
from seahorse_ai.schemas import AgentRequest

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class SeahorseDiscordClient(discord.Client):
    def __init__(self, planner: ReActPlanner, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = planner

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info("------")

    async def on_message(self, message: discord.Message):
        # Debug log: Every time a message is seen
        logger.debug(f"Event: on_message triggered by {message.author}. Content length: {len(message.content)}")

        # Don't respond to ourselves
        if message.author == self.user:
            return

        # Check if we were mentioned
        was_mentioned = self.user and self.user.mentioned_in(message)
        is_dm = isinstance(message.channel, discord.DMChannel)

        if was_mentioned or is_dm:
            # If we were mentioned but content is empty, it's likely the Message Content Intent is missing
            if not message.content.strip():
                logger.warning(
                    "⚠️ Received a mention but message CONTENT is empty. "
                    "Did you forget to enable 'Message Content Intent' in the Discord Developer Portal?"
                )
                if is_dm:
                    await message.channel.send("❌ บอทไม่เห็นข้อความครับ รบกวนเจ้าของบอทเปิด 'Message Content Intent' ใน Developer Portal ด้วยครับ")
                return

            # Clean up the message (remove mention)
            prompt = message.content
            if self.user and self.user.mentioned_in(message):
                prompt = prompt.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()

            if not prompt:
                return

            logger.info(f"Discord: Received message from {message.author}: {prompt}")
            
            async with message.channel.typing():
                try:
                    request = AgentRequest(
                        prompt=prompt,
                        agent_id=f"discord_{message.author.id}"
                    )
                    response = await self.planner.run(request)
                    
                    # Discord has a 2000 character limit per message
                    content = response.content
                    if len(content) > 1900:
                        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
                        for chunk in chunks:
                            await message.channel.send(chunk)
                    else:
                        await message.channel.send(content)
                        
                except Exception as e:
                    logger.error(f"Error processing Discord message: {e}")
                    await message.channel.send(f"❌ Error: {str(e)}")

async def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not found in environment.")
        return

    # Initialize MoE Router and Planner
    # Models are loaded from .env or fallback to Gemini/Claude
    router = ModelRouter(
        worker_model=os.environ.get("SEAHORSE_MODEL_WORKER", "openrouter/google/gemini-2.0-flash-001"),
        thinker_model=os.environ.get("SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-2.0-flash-001"),
        strategist_model=os.environ.get("SEAHORSE_MODEL_STRATEGIST", "openrouter/anthropic/claude-3.5-sonnet")
    )
    planner = ReActPlanner(llm=router)

    # Initialize Discord Client
    intents = discord.Intents.default()
    intents.message_content = True  # Required to read message content
    
    client = SeahorseDiscordClient(planner=planner, intents=intents)
    
    async with client:
        await client.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Discord bot stopped.")
