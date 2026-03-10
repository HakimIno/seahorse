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
import contextlib
import logging
import os
import re
import sys
from collections import defaultdict, deque

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

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
    """Adapter for Telegram Bot API integration."""

    def __init__(self, router_url: str = "http://localhost:8000") -> None:
        """Initialize adapter with router URL."""
        self.router_url = router_url
        self._history: dict[int, deque[Message]] = defaultdict(
            lambda: deque(maxlen=_MAX_HISTORY)
        )
        self._callback_data_map = {}

    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global debug handler for all updates."""
        logger.info("Telegram RAW Update: %s", update.to_dict())

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text("สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลธุรกิจแล้วครับ")

    async def id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Reply with the current Chat ID."""
        msg = update.message or update.channel_post
        if not msg:
            return
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        await self._safe_send_message(
            context,
            chat_id,
            f"📍 **Chat Info**\nID: `{chat_id}`\nType: {chat_type}",
            parse_mode=ParseMode.MARKDOWN
        )

    async def _safe_send_message(
        self, 
        context: ContextTypes.DEFAULT_TYPE, 
        chat_id: int, 
        text: str, 
        **kwargs: object
    ) -> None:
        """Send a message with Markdown, falling back to plain text if parsing fails."""
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            logger.warning(
                "Telegram: Markdown failed for message, falling back to plain text: %s", e
            )
            kwargs.pop("parse_mode", None)
            return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
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
        logger.info("Telegram: Update in %s (%s): %s", chat_id, chat_type, text)

        if text.strip().startswith("/id"):
            await self.id_command(update, context)
            return

        if not text:
            return

        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"
        
        await self._process_text_input(update, context, text, chat_id, user_id, agent_id)

    async def _process_text_input(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE, 
        text: str, 
        chat_id: int, 
        user_id: int, 
        agent_id: str
    ) -> None:
        """Core logic for processing user input and generating responses."""
        try:
            # Clean history: Merge consecutive messages with the same role
            # This is required by some providers like Z-AI (GLM)
            raw_history = list(self._history[user_id])
            cleaned_history = []
            for msg in raw_history:
                if cleaned_history and cleaned_history[-1].role == msg.role:
                    cleaned_history[-1].content += f"\n\n{msg.content}"
                else:
                    cleaned_history.append(msg)
            
            request = AgentRequest(
                prompt=text,
                agent_id=agent_id,
                history=cleaned_history,
            )

            async def keep_typing() -> None:
                try:
                    while True:
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        await asyncio.sleep(3.0)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(keep_typing())
            await asyncio.sleep(0)

            try:
                # UNIFIED: Redirect to Rust Router instead of local ReActPlanner
                async with httpx.AsyncClient(timeout=300.0) as client:
                    # Optimization: Send only a small window of history (e.g., last 5 messages) 
                    # to the Router for Fast Path checks to save tokens on every turn.
                    fast_path_history = (
                        list(cleaned_history)[-5:] 
                        if len(cleaned_history) > 5 
                        else list(cleaned_history)
                    )
                    
                    resp = await client.post(
                        f"{self.router_url}/v1/agent/run",
                        json={
                            "prompt": text,
                            "agent_id": agent_id,
                            "history": [m.model_dump() for m in fast_path_history]
                        }
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    
                    # Wrap internal response format
                    from seahorse_ai.schemas import AgentResponse
                    
                    # If Fast Path handled it, we get content directly
                    if data.get("status") == "completed" and data.get("content"):
                        response = AgentResponse(
                            content=data["content"],
                            steps=0,
                            agent_id=agent_id,
                            elapsed_ms=0
                        )
                    else:
                        # If not Fast Path, fall back to local planner for immediate response
                        logger.info("FastPath: [FALLBACK] or Queued. Using local ReActPlanner.")
                        from seahorse_ai.planner import ReActPlanner
                        from seahorse_ai.router import ModelRouter
                        internal_router = ModelRouter(
                            worker_model=os.environ.get(
                                "SEAHORSE_MODEL_WORKER",
                                "openrouter/google/gemini-3-flash-preview"
                            ),
                            thinker_model=os.environ.get(
                                "SEAHORSE_MODEL_THINKER",
                                "openrouter/google/gemini-3-flash-preview"
                            ),
                            strategist_model=os.environ.get(
                                "SEAHORSE_MODEL_STRATEGIST",
                                "openrouter/google/gemini-3-flash-preview"
                            ),
                        )
                        local_planner = ReActPlanner(llm=internal_router)
                        response = await local_planner.run(request)

            except Exception as e:
                logger.error(
                    "Failed to connect to Rust Router: %s. Falling back to internal planner…", e
                )
                # Fallback to local planner if router is down
                from seahorse_ai.planner import ReActPlanner
                from seahorse_ai.router import ModelRouter
                internal_router = ModelRouter(
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
                local_planner = ReActPlanner(llm=internal_router)
                response = await local_planner.run(request)
            finally:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

            self._history[user_id].append(Message(role="user", content=text))
            self._history[user_id].append(Message(role="assistant", content=response.content))

            content = response.content
            choices = _extract_choices(content)

            reply_markup = None
            if choices:
                keyboard = []
                for i, choice in enumerate(choices):
                    cb_key = f"c_{user_id}_{i}"
                    self._callback_data_map[cb_key] = choice
                    keyboard.append([InlineKeyboardButton(choice, callback_data=cb_key)])
                reply_markup = InlineKeyboardMarkup(keyboard)

            if hasattr(response, "image_paths") and response.image_paths:
                for path in response.image_paths:
                    if os.path.exists(path):
                        try:
                            with open(path, "rb") as photo:
                                await context.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=photo,
                                    caption=content if len(content) < 1024 else None,
                                    parse_mode=ParseMode.MARKDOWN,
                                )
                        except Exception as e:
                            if "Can't parse entities" in str(e):
                                logger.warning("Telegram: Photo caption Markdown failed, falling back")
                                with open(path, "rb") as photo:
                                    await context.bot.send_photo(
                                        chat_id=chat_id,
                                        photo=photo,
                                        caption=content if len(content) < 1024 else None,
                                    )
                            else:
                                raise e
                        
                        if len(content) >= 1024:
                            await self._safe_send_message(
                                context,
                                chat_id,
                                content, 
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.MARKDOWN
                            )
                        return

            await self._safe_send_message(
                context,
                chat_id,
                content, 
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.exception("Error processing Telegram input in %s:", agent_id)
            clean_error = str(e).split(":")[0]
            # Escape error text to avoid Markdown issues in error reporting
            clean_error = clean_error.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ ผมพบปัญหาขัดข้องชั่วคราว: {clean_error}"
            )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button clicks."""
        query = update.callback_query
        if not query or not query.data:
            return
        
        await query.answer()
        
        cb_key = query.data
        choice = self._callback_data_map.get(cb_key, cb_key)
        
        chat_id = update.effective_chat.id
        logger.info("Telegram: Callback from %s: %s (key: %s)", chat_id, choice, cb_key)
        
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)
            
            await self._safe_send_message(
                context,
                chat_id,
                f"_{choice}_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Simulate trigger without modifying update.message
            user_id = update.effective_user.id if update.effective_user else chat_id
            agent_id = f"telegram_{user_id}"
            await self._process_text_input(update, context, choice, chat_id, user_id, agent_id)

    async def send_proactive_alert(self, data: dict[str, object]) -> None:
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
                    try:
                        with open(path, "rb") as photo:
                            await bot.send_photo(
                                chat_id=chat_id,
                                photo=photo,
                                caption=message_content,
                                parse_mode=ParseMode.MARKDOWN,
                            )
                    except Exception as e:
                        if "Can't parse entities" in str(e):
                            with open(path, "rb") as photo:
                                await bot.send_photo(
                                    chat_id=chat_id, photo=photo, caption=message_content
                                )
                        else:
                            raise e
                    return
            
            try:
                await bot.send_message(
                    chat_id=chat_id, text=message_content, parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                if "Can't parse entities" in str(e):
                    await bot.send_message(chat_id=chat_id, text=message_content)
                else:
                    raise e
        except Exception as e:
            logger.error("Failed to send Telegram proactive alert: %s", e)

def main() -> None:
    """Launch the Telegram bot application."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found.")
        return

    adapter = TelegramAdapter(router_url=os.environ.get("SEAHORSE_ROUTER_URL", "http://localhost:8000"))

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

    app = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(60.0)
        .read_timeout(360.0)
        .write_timeout(120.0)
        .pool_timeout(120.0)
        .build()
    )

    app.add_handler(TypeHandler(Update, adapter.handle_update), group=-1)

    app.add_handler(CommandHandler("start", adapter.start_command))
    app.add_handler(CommandHandler("id", adapter.id_command))
    
    app.add_handler(MessageHandler(filters.ALL, adapter.handle_message))
    
    app.add_handler(CallbackQueryHandler(adapter.handle_callback))

    from seahorse_ai.analysis.watcher import AnomalyWatcher
    watcher = AnomalyWatcher(llm_backend=router)
    watcher._notify = adapter.send_proactive_alert
    
    async def post_init(application: any) -> None:
        interval = int(os.environ.get("SEAHORSE_ALERTS_INTERVAL", "300"))
        asyncio.create_task(watcher.start(interval_seconds=interval))
        logger.info("Telegram: AnomalyWatcher task started via post_init.")

    app.post_init = post_init

    logger.info("Telegram bot starting via run_polling...")
    
    app.run_polling(
        allowed_updates=[
            "message", "channel_post", "callback_query", 
            "edited_message", "edited_channel_post"
        ],
        bootstrap_retries=5
    )

if __name__ == "__main__":
    main()
