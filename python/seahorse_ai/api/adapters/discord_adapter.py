"""seahorse_ai.api.adapters.discord_adapter — Discord bot adapter for Seahorse.

Features:
- Per-user conversation history buffer (rolling 20 messages)
- Interactive clarification buttons (discord.ui.View) when AI shows numbered choices
- Auto-submits user's button choice back into the conversation as a message

Usage:
    export DISCORD_BOT_TOKEN=your_token
    uv run python -m seahorse_ai.api.adapters.discord_adapter
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections import defaultdict, deque

import anyio
import discord
import discord.ui

from seahorse_ai.analysis.watcher import AnomalyWatcher
from seahorse_ai.core.router import ModelRouter
from seahorse_ai.core.schemas import AgentRequest, Message
from seahorse_ai.planner import ReActPlanner

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

_MAX_HISTORY: int = int(os.environ.get("SEAHORSE_DISCORD_HISTORY", "20"))

# Pattern to detect numbered options in AI responses
# Matches: "1. Option A" or "1) Option A"
_CHOICE_PATTERN = re.compile(r"(?:^|\n)\s*(?:\d+[.)]\s+)(.+)", re.MULTILINE)


def _extract_choices(text: str) -> list[str]:
    """Extract numbered/bulleted choices from an AI response.

    Returns a list of option labels, or [] if no choices found.
    Only extracts if there are 2-5 options (otherwise it's a regular list).
    """
    matches = _CHOICE_PATTERN.findall(text)
    # Filter: must be short labels (not multi-sentence paragraphs)
    choices = [m.strip() for m in matches if len(m.strip()) < 80]
    return choices if 2 <= len(choices) <= 5 else []


# ── Discord UI Components ──────────────────────────────────────────────────────


class ClarificationView(discord.ui.View):
    """A Discord View with dynamic buttons for each choice option.

    When a button is clicked, it:
    1. Disables all buttons (prevents double-click)
    2. Sends the selected option back to the agent as a new message
    """

    def __init__(
        self,
        choices: list[str],
        planner: ReActPlanner,
        history: deque[Message],
        agent_id: str,
        channel: discord.TextChannel,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._planner = planner
        self._history = history
        self._agent_id = agent_id
        self._channel = channel
        self._choices = choices

        # Add a button for each choice (max 5 per row)
        colors = [
            discord.ButtonStyle.primary,  # Blue
            discord.ButtonStyle.secondary,  # Grey
            discord.ButtonStyle.success,  # Green
            discord.ButtonStyle.danger,  # Red
            discord.ButtonStyle.primary,
        ]
        for i, choice in enumerate(choices[:5]):
            # Truncate label to Discord's 80-char limit
            label = choice[:77] + "..." if len(choice) > 80 else choice
            btn = discord.ui.Button(
                label=label,
                style=colors[i % len(colors)],
                custom_id=f"choice_{i}",
                row=0,
            )
            btn.callback = self._make_callback(choice)
            self.add_item(btn)

    def _make_callback(self, choice: str):
        """Create a callback for a specific choice button."""

        async def callback(interaction: discord.Interaction) -> None:
            # Acknowledge the interaction immediately (must be within 3 seconds)
            # If the interaction has expired (bot reconnect / slow), handle gracefully
            try:
                await interaction.response.defer()
                acknowledged = True
            except (discord.errors.NotFound, discord.errors.HTTPException):
                # Interaction expired — still process the choice via channel fallback
                acknowledged = False
                logger.warning(
                    "Interaction expired for choice '%s' — falling back to channel send", choice
                )

            # Disable all buttons to prevent re-clicking
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            try:
                if acknowledged:
                    await interaction.message.edit(view=self)
                else:
                    await self._channel.send("⚠️ Interaction หมดอายุ แต่ยังดำเนินการต่อ...")
            except Exception:
                pass  # Best-effort button disable

            # Show user's selection visually
            await self._channel.send(f"✅ **เลือก:** {choice}")

            # Send the choice back through the planner as a follow-up message
            async with self._channel.typing():
                try:
                    history = list(self._history)
                    request = AgentRequest(
                        prompt=choice,
                        agent_id=self._agent_id,
                        history=history,
                    )
                    response = await self._planner.run(request)

                    # Update history with this interaction
                    self._history.append(Message(role="user", content=choice))
                    self._history.append(Message(role="assistant", content=response.content))

                    content = response.content
                    if len(content) > 1900:
                        chunks = [content[i : i + 1900] for i in range(0, len(content), 1900)]
                        for chunk in chunks:
                            await self._channel.send(chunk)
                    else:
                        await self._channel.send(content)

                except Exception as e:
                    logger.error("Error processing button choice: %s", e)
                    await self._channel.send(f"❌ Error: {str(e)}")

        return callback

    async def on_timeout(self) -> None:
        """Disable buttons when the view times out."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        logger.info("ClarificationView timed out for agent_id=%s", self._agent_id)


# ── Discord Client ─────────────────────────────────────────────────────────────


class SeahorseDiscordClient(discord.Client):
    def __init__(self, planner: ReActPlanner, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.planner = planner
        # Per-user conversation history: user_id → deque of Message
        self._history: dict[str, deque[Message]] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY))

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logger.info("Seahorse AI: Proactive monitoring active.")
        logger.info("------")

    async def send_proactive_alert(self, data: dict) -> None:
        """Send a proactive business alert to the first available text channel."""
        try:
            severity_emoji = "🚨" if data.get("severity") == "high" else "⚠️"
            title = data.get("title", "Business Update")
            reason = data.get("reason", "No details available.")

            message_content = (
                f"{severity_emoji} **PROACTIVE INSIGHT: {title}**\n\n"
                f"{reason}\n\n"
                f"*ต้องการให้ผมเจาะลึกข้อมูลส่วนนี้ไหมครับ?*"
            )

            # Find a channel to post to
            # Priority: SEAHORSE_ALERTS_CHANNEL_ID env var, then first guild's first text channel
            channel_id = os.environ.get("SEAHORSE_ALERTS_CHANNEL_ID")
            target_channel = None

            if channel_id:
                target_channel = self.get_channel(int(channel_id))

            if not target_channel:
                for guild in self.guilds:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            target_channel = channel
                            break
                    if target_channel:
                        break

            if target_channel:
                files = []
                # Handle single path (legacy) or list of paths
                image_paths = data.get("image_paths", [])
                legacy_path = data.get("image_path")
                if legacy_path and legacy_path not in image_paths:
                    image_paths.append(legacy_path)

                for path in image_paths:
                    if path and os.path.exists(path):
                        files.append(discord.File(path))

                await target_channel.send(message_content, files=files if files else None)
                logger.info("Proactive alert sent to channel: %s", target_channel.name)
            else:
                logger.warning("Could not find a suitable channel for proactive alert.")

        except Exception as e:
            logger.error("Failed to send proactive alert: %s", e)

    async def on_message(self, message: discord.Message) -> None:
        logger.debug(
            "Event: on_message triggered by %s. Content length: %d",
            message.author,
            len(message.content),
        )

        if message.author == self.user:
            return

        was_mentioned = self.user and self.user.mentioned_in(message)
        is_dm = isinstance(message.channel, discord.DMChannel)

        if was_mentioned or is_dm:
            if not message.content.strip():
                logger.warning(
                    "⚠️ Received a mention but message CONTENT is empty. "
                    "Did you forget to enable 'Message Content Intent'?"
                )
                if is_dm:
                    await message.channel.send(
                        "❌ บอทไม่เห็นข้อความครับ รบกวนเจ้าของบอทเปิด "
                        "'Message Content Intent' ใน Developer Portal ด้วยครับ"
                    )
                return

            prompt = message.content
            if self.user and self.user.mentioned_in(message):
                prompt = (
                    prompt.replace(f"<@{self.user.id}>", "")
                    .replace(f"<@!{self.user.id}>", "")
                    .strip()
                )

            if not prompt:
                return

            user_id = str(message.author.id)
            agent_id = f"discord_{user_id}"
            logger.info("Discord: Received message from %s: %s", message.author, prompt)

            async with message.channel.typing():
                try:
                    history = list(self._history[user_id])
                    request = AgentRequest(
                        prompt=prompt,
                        agent_id=agent_id,
                        history=history,
                    )
                    response = await self.planner.run(request)

                    # Update history
                    self._history[user_id].append(Message(role="user", content=prompt))
                    self._history[user_id].append(
                        Message(role="assistant", content=response.content)
                    )

                    content = response.content

                    files = []
                    if getattr(response, "image_paths", None):
                        for path in response.image_paths:
                            if os.path.exists(path):
                                files.append(discord.File(path))

                    # ── Check if response has interactive choices ──────────
                    choices = _extract_choices(content)
                    if choices:
                        view = ClarificationView(
                            choices=choices,
                            planner=self.planner,
                            history=self._history[user_id],
                            agent_id=agent_id,
                            channel=message.channel,
                        )
                        # Send message with interactive buttons
                        if len(content) > 1900:
                            # Send text first, then buttons on a short follow-up
                            intro = content[:1900]
                            await message.channel.send(intro, files=files if files else None)
                            await message.channel.send("เลือกตัวเลือก:", view=view)
                        else:
                            await message.channel.send(
                                content, view=view, files=files if files else None
                            )
                    else:
                        # Regular text response
                        if len(content) > 1900:
                            chunks = [content[i : i + 1900] for i in range(0, len(content), 1900)]
                            for i, chunk in enumerate(chunks):
                                # Attach files only to the first chunk to avoid sending duplicates
                                if i == 0 and files:
                                    await message.channel.send(chunk, files=files)
                                else:
                                    await message.channel.send(chunk)
                        else:
                            await message.channel.send(content, files=files if files else None)

                except Exception as e:
                    logger.error("Error processing Discord message: %s", e)
                    await message.channel.send(f"❌ Error: {str(e)}")


async def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not found in environment.")
        return

    router = ModelRouter(
        worker_model=os.environ.get(
            "SEAHORSE_MODEL_WORKER", "openrouter/google/gemini-3-flash-preview"
        ),
        thinker_model=os.environ.get(
            "SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-3-flash-preview"
        ),
        strategist_model=os.environ.get(
            "SEAHORSE_MODEL_STRATEGIST", "openrouter/google/gemini-3-flash-preview"
        ),
    )
    planner = ReActPlanner(llm=router)

    intents = discord.Intents.default()
    intents.message_content = True

    client = SeahorseDiscordClient(planner=planner, intents=intents)

    # Initialize AnomalyWatcher
    watcher = AnomalyWatcher(llm_backend=router)
    # Redirect watcher notifications to our Discord client
    watcher._notify = client.send_proactive_alert  # type: ignore

    interval = int(os.environ.get("SEAHORSE_ALERTS_INTERVAL", "300"))

    async with client:
        # Start watcher and client in parallel using AnyIO TaskGroup
        async with anyio.create_task_group() as tg:
            tg.start_soon(watcher.start, interval)
            tg.start_soon(client.start, token)


if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        logger.info("Discord bot stopped.")
