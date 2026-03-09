"""seahorse_ai.adapters.telegram_adapter — Telegram bot adapter for Seahorse.

Features:
- Per-user conversation history buffer (rolling 20 messages)
- Inline keyboard for numbered choices
- Proactive business alerts with charts

Usage:
    export TELEGRAM_BOT_TOKEN=your_token
    uv run python -m seahorse_ai.adapters.telegram_adapter
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections import defaultdict, deque

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    TypeHandler,
)
from telegram.constants import ParseMode

from seahorse_ai.planner import ReActPlanner
from seahorse_ai.router import ModelRouter
from seahorse_ai.schemas import AgentRequest, Message

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

_MAX_HISTORY: int = int(os.environ.get("SEAHORSE_TELEGRAM_HISTORY", "20"))

# Pattern to detect numbered options in AI responses
_CHOICE_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d+[.)]\s+)(.+)",
    re.MULTILINE
)

def _extract_choices(text: str) -> list[str]:
    """Extract numbered/bulleted choices from an AI response."""
    matches = _CHOICE_PATTERN.findall(text)
    choices = [m.strip() for m in matches if len(m.strip()) < 80]
    return choices if 2 <= len(choices) <= 5 else []

class TelegramAdapter:
    def __init__(self, planner: ReActPlanner):
        self.planner = planner
        self._history: dict[int, deque[Message]] = defaultdict(
            lambda: deque(maxlen=_MAX_HISTORY)
        )

    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Global debug handler for all updates."""
        logger.info("Telegram RAW Update: %s", update.to_dict())

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลธุรกิจแล้วครับ")

    async def id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reply with the current Chat ID."""
        msg = update.message or update.channel_post
        if not msg:
            return
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        await msg.reply_text(
            f"📍 **Chat Info**\nID: `{chat_id}`\nType: {chat_type}",
            parse_mode=ParseMode.MARKDOWN
        )

    async def handle_message(self
, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            update.message 
            or update.channel_post 
            or update.edited_message 
            or update.edited_channel_post
        )
        if not msg:
            return

        text = msg.text or msg.caption or ""
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        logger.info(
            "Telegram: Update in %s (%s): %s", 
            chat_id, chat_type, text
        )

        # Emergency handle for /id
        if text.strip().startswith("/id"):
            await self.id_command(update, context)
            return

        if not text:
            return

        # Fallback to chat_id if no user (common in channels)
        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"

        try:
            # Prepare request
            history = list(self._history[user_id])
            request = AgentRequest(
                prompt=text,
                agent_id=agent_id,
                history=history,
            )

            # Continuous typing indicator task
            async def keep_typing():
                logger.info("Telegram: Started keep_typing loop for chat %s", chat_id)
                ping_count = 0
                try:
                    while True:
                        ping_count += 1
                        try:
                            logger.info("Telegram: keep_typing ping #%d", ping_count)
                            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        except Exception as e:
                            logger.error("Telegram: keep_typing send error: %s", e)
                        
                        # Telegram's typing indicator lasts 5 seconds, ping every 3
                        # We use 3.0 to give plenty of buffer
                        await asyncio.sleep(3.0)
                except asyncio.CancelledError:
                    logger.info("Telegram: keep_typing loop cancelled after %d pings", ping_count)

            typing_task = asyncio.create_task(keep_typing())
            # Yield control immediately so the task can start its first ping
            await asyncio.sleep(0)

            try:
                response = await self.planner.run(request)
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

            # Update history
            self._history[user_id].append(Message(role="user", content=text))
            self._history[user_id].append(Message(role="assistant", content=response.content))

            content = response.content
            choices = _extract_choices(content)

            reply_markup = None
            if choices:
                keyboard = []
                for i, choice in enumerate(choices):
                    # Telegram limit is 64 bytes for callback_data
                    # We use a unique key per user/session
                    cb_key = f"c_{user_id}_{i}"
                    self._callback_data_map[cb_key] = choice
                    keyboard.append([InlineKeyboardButton(choice, callback_data=cb_key)])
                reply_markup = InlineKeyboardMarkup(keyboard)

            # Send files if any
            if hasattr(response, "image_paths") and response.image_paths:
                for path in response.image_paths:
                    if os.path.exists(path):
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=open(path, 'rb'),
                            caption=content if len(content) < 1024 else None,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        if len(content) >= 1024:
                            await msg.reply_text(
                                content, 
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.MARKDOWN
                            )
                        return

            await msg.reply_text(
                content, 
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error("Error processing Telegram message: %s", e)
            # Avoid sending long technical errors to user
            clean_error = str(e).split(":")[0]
            await msg.reply_text(f"❌ ผมพบปัญหาขัดข้องชั่วคราว: {clean_error}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks."""
        query = update.callback_query
        if not query or not query.data:
            return
        
        await query.answer()
        
        cb_key = query.data
        choice = self._callback_data_map.get(cb_key, cb_key) # Fallback to key if not found
        
        chat_id = update.effective_chat.id
        logger.info("Telegram: Callback from %s: %s (key: %s)", chat_id, choice, cb_key)
        
        # We simulate a new message from the user
        # Instead of just calling handle_message, we create a pseudo-update 
        # to ensure it flows through correctly
        if query.message:
            # Edit original message to remove buttons (UX improvement)
            await query.edit_message_reply_markup(reply_markup=None)
            
            # Send the choice as if user typed it
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"_{choice}_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Now trigger the brain
            # Create a mock update for handle_message
            update.message = query.message
            update.message.text = choice
            # We must set effector user correctly for agent_id
            await self.handle_message(update, context)

    async def send_proactive_alert(self, data: dict):
        """Send a proactive alert to any configured chat."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_ALERTS_CHAT_ID")
        
        if not token or not chat_id:
            return

        from telegram import Bot
        bot = Bot(token=token)

        try:
            severity_emoji = "🚨" if data.get("severity") == "high" else "⚠️"
            title = data.get("title", "Business Update")
            reason = data.get("reason", "No details available.")
            
            message_content = (
                f"{severity_emoji} **PROACTIVE INSIGHT: {title}**\n\n"
                f"{reason}\n\n"
                f"*ต้องการให้ผมเจาะลึกข้อมูลส่วนนี้ไหมครับ?*"
            )

            image_paths = data.get("image_paths", [])
            for path in image_paths:
                if os.path.exists(path):
                    await bot.send_photo(
                        chat_id=chat_id, 
                        photo=open(path, 'rb'), 
                        caption=message_content, 
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            await bot.send_message(chat_id=chat_id, text=message_content, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error("Failed to send Telegram proactive alert: %s", e)

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found.")
        return

    router = ModelRouter(
        worker_model=os.environ.get("SEAHORSE_MODEL_WORKER"),
        thinker_model=os.environ.get("SEAHORSE_MODEL_THINKER"),
        strategist_model=os.environ.get("SEAHORSE_MODEL_STRATEGIST"),
    )
    planner = ReActPlanner(llm=router)
    adapter = TelegramAdapter(planner)

    app = ApplicationBuilder().token(token).build()

    # Global Debug Handler (catches EVERYTHING)
    app.add_handler(TypeHandler(Update, adapter.handle_update), group=-1)

    # Handlers
    app.add_handler(CommandHandler("start", adapter.start_command))
    app.add_handler(CommandHandler("id", adapter.id_command))
    
    # Explicitly handle all message types
    app.add_handler(MessageHandler(filters.ALL, adapter.handle_message))
    
    app.add_handler(CallbackQueryHandler(adapter.handle_callback))

    # Anomaly Watcher
    from seahorse_ai.analysis.watcher import AnomalyWatcher
    watcher = AnomalyWatcher(llm_backend=router)
    watcher._notify = adapter.send_proactive_alert
    
    # We use post_init to start the watcher task inside the application loop
    async def post_init(application) -> None:
        interval = int(os.environ.get("SEAHORSE_ALERTS_INTERVAL", "300"))
        asyncio.create_task(watcher.start(interval_seconds=interval))
        logger.info("Telegram: AnomalyWatcher task started via post_init.")

    app.post_init = post_init

    logger.info("Telegram bot starting via run_polling...")
    
    # Standard blocking polling
    app.run_polling(allowed_updates=[
        "message", "channel_post", "callback_query", 
        "edited_message", "edited_channel_post"
    ])

if __name__ == "__main__":
    main()
