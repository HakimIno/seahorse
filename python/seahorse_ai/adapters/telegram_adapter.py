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

import json
import logging
import os
import re
import sys
import uuid
from collections import defaultdict, deque

import anyio
import httpx
import msgspec
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
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

_MAX_HISTORY: int = int(os.environ.get("SEAHORSE_TELEGRAM_HISTORY", "20"))

# Pattern to detect numbered options in AI responses
# Choice pattern
_CHOICE_PATTERN = re.compile(r"(?:^|\n)\s*(?:\d+[.)]\s+)(.+)", re.MULTILINE)

# Directory for uploaded files
UPLOAD_DIR = "/tmp/seahorse_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _extract_choices(text: str) -> list[str]:
    """Extract numbered/bulleted choices from an AI response."""
    matches = _CHOICE_PATTERN.findall(text)
    choices = [m.strip() for m in matches if len(m.strip()) < 80]
    return choices if 2 <= len(choices) <= 5 else []


def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown (V1)."""
    # Telegram Markdown (V1) only needs escaping for characters that start an entity
    # if they are not intended to be one.
    # We focus on the big ones that usually break things: _, *, `
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")


class TelegramAdapter:
    """Adapter for Telegram Bot API integration."""

    def __init__(self, router_url: str = "http://localhost:8000") -> None:
        """Initialize adapter with router URL."""
        self.router_url = router_url
        self._history: dict[int, deque[Message]] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY))
        self._callback_data_map = {}
        self._user_files: dict[int, list[str]] = defaultdict(list)
        
        # Configuration for specialized bots
        self.welcome_message = os.environ.get(
            "SEAHORSE_TELEGRAM_WELCOME", 
            "สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลธุรกิจแล้วครับ"
        )
        self.system_nudge = os.environ.get("SEAHORSE_TELEGRAM_NUDGE", "")

    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global debug handler for all updates."""
        logger.info("Telegram RAW Update: %s", update.to_dict())

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(self.welcome_message)

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
            parse_mode=ParseMode.MARKDOWN,
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command to show performance report."""
        if os.environ.get("SEAHORSE_ENABLE_FOOTBALL") != "true":
            await update.message.reply_text("⚽ Football stats are currently disabled.")
            return
            
        from seahorse_ai.analysis.football_eval import get_performance_stats
        
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        report = await get_performance_stats()
        await self._safe_send_message(
            context,
            chat_id,
            report,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def reflect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reflect command to consolidate memory."""
        from seahorse_ai.tools.memory import memory_reflect
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"
        
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        result = await memory_reflect(agent_id=agent_id)
        await self._safe_send_message(
            context,
            chat_id,
            f"🧠 **Hindsight Reflection**\n{result}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def remember_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /remember command to explicitly store a fact."""
        from seahorse_ai.tools.memory import memory_store
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"
        
        # Extract text after /remember
        text = " ".join(context.args) if context.args else ""
        if not text:
            await update.message.reply_text("💡 โปรดใส่ข้อความที่ต้องการให้จำ เช่น: `/remember พรุ่งนี้มีประชุมตอน 10 โมง`", parse_mode=ParseMode.MARKDOWN)
            return

        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        result = await memory_store(text, agent_id=agent_id)
        await self._safe_send_message(
            context,
            chat_id,
            f"✅ **จดจำสำเร็จ**\n{result}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /search command to query memory."""
        from seahorse_ai.tools.memory import memory_search
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"
        
        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("🔍 โปรดใส่ข้อความที่ต้องการค้นหา เช่น: `/search ประชุมครั้งที่แล้วคุยเรื่องอะไร`", parse_mode=ParseMode.MARKDOWN)
            return

        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        results = await memory_search(query, agent_id=agent_id)
        
        if isinstance(results, str):
            response = results
        else:
            response = "🔍 **ผลการค้นหาจากความจำ:**\n\n"
            for i, res in enumerate(results[:5]):
                content = res.get("content", res.get("text", "No content"))
                score = res.get("score", 0.0)
                category = res.get("category", "WORLD")
                response += f"{i+1}. [{category}] (Score: {score:.3f})\n{content}\n\n"

        await self._safe_send_message(
            context,
            chat_id,
            response,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _safe_send_message(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs: object
    ) -> None:
        """Send a message with Markdown, falling back to plain text if parsing fails.
        Splits long messages into chunks to avoid 'Message is too long' error.
        """
        # Split text into chunks of ~4000 characters
        max_chunk = 4000
        chunks = [text[i : i + max_chunk] for i in range(0, len(text), max_chunk)]
        
        for chunk in chunks:
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk, **kwargs)
            except Exception as e:
                logger.warning(
                    "Telegram: Markdown failed for message chunk, falling back to plain text: %s", e
                )
                kwargs.pop("parse_mode", None)
                await context.bot.send_message(chat_id=chat_id, text=chunk, **kwargs)

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
        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"

        # Handle File Uploads
        file_info = ""
        if msg.document:
            try:
                doc = msg.document
                file_name = doc.file_name or f"upload_{uuid.uuid4().hex[:8]}"
                save_path = os.path.join(UPLOAD_DIR, file_name)
                
                # Get file from Telegram
                tg_file = await context.bot.get_file(doc.file_id)
                await tg_file.download_to_drive(custom_path=save_path)
                
                logger.info(f"Telegram: File saved to {save_path}")
                # Store in session for persistence
                if save_path not in self._user_files[user_id]:
                    self._user_files[user_id].append(save_path)
                
                file_info = f"\n\n[SYSTEM: User uploaded a file to {save_path}. You can use tools to read it.]"
            except Exception as e:
                logger.error(f"Telegram: File download failed: {e}")
                await update.message.reply_text(f"❌ ไม่สามารถดาวน์โหลดไฟล์ได้: {e}")

        if text.strip().startswith("/id"):
            await self.id_command(update, context)
            return

        if not text:
            return

        user_id = update.effective_user.id if update.effective_user else chat_id
        agent_id = f"telegram_{user_id}"

        # Inject ALL previously uploaded files in the session to prevent hallucination
        if self._user_files.get(user_id):
            active_files = ", ".join(self._user_files[user_id])
            context_nudge = f"\n\n[SYSTEM: Active files in this session: {active_files}. USE THESE instead of sample data!]"
            if not file_info: # Don't double-add if we just uploaded a new one
                text += context_nudge

        await self._process_text_input(update, context, text, chat_id, user_id, agent_id)

    async def _process_text_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        chat_id: int,
        user_id: int,
        agent_id: str,
    ) -> None:
        """Core logic for processing user input and generating responses."""
        try:
            # Clean history: Merge consecutive messages with the same role
            raw_history = list(self._history[user_id])
            cleaned_history = []
            for msg in raw_history:
                if cleaned_history and cleaned_history[-1].role == msg.role:
                    cleaned_history[-1].content += f"\n\n{msg.content}"
                else:
                    cleaned_history.append(msg)

            # Inject system nudge if configured
            final_prompt = text
            if self.system_nudge:
                final_prompt = f"{self.system_nudge}\n\nUser Question: {text}"

            request = AgentRequest(
                prompt=final_prompt,
                agent_id=agent_id,
                history=cleaned_history,
            )

            async def keep_typing() -> None:
                try:
                    while True:
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        await anyio.sleep(3.0)
                except Exception:
                    pass

            async with anyio.create_task_group() as tg:
                tg.start_soon(keep_typing)

                try:
                    # UNIFIED: Redirect to Rust Router instead of local ReActPlanner
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        fast_path_history = (
                            list(cleaned_history)[-5:]
                            if len(cleaned_history) > 5
                            else list(cleaned_history)
                        )

                        resp = await client.post(
                            f"{self.router_url}/v1/agent/run",
                            json={
                                "prompt": final_prompt,
                                "agent_id": agent_id,
                                "history": [msgspec.to_builtins(m) for m in fast_path_history],
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()

                        if data.get("status") == "completed" and data.get("content"):
                            response = AgentResponse(
                                content=data["content"], steps=0, agent_id=agent_id, elapsed_ms=0
                            )
                        else:
                            logger.info("FastPath: [FALLBACK] or Queued. Using local ReActPlanner.")
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
                                    "SEAHORSE_MODEL_STRATEGIST",
                                    "openrouter/google/gemini-3-flash-preview",
                                ),
                                fast_path_model=os.environ.get(
                                    "SEAHORSE_FAST_PATH_MODEL",
                                    "openrouter/google/gemini-3.1-flash-lite-preview",
                                ),
                            )
                            local_planner = ReActPlanner(llm=internal_router)
                            response = await local_planner.run(request)

                except Exception as e:
                    logger.error(
                        "Failed to connect to Rust Router: %s. Falling back to internal planner…", e
                    )
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
                        fast_path_model=os.environ.get(
                            "SEAHORSE_FAST_PATH_MODEL",
                            "openrouter/google/gemini-3.1-flash-lite-preview",
                        ),
                    )
                    local_planner = ReActPlanner(llm=internal_router)
                    response = await local_planner.run(request)
                finally:
                    tg.cancel_scope.cancel()

            self._history[user_id].append(Message(role="user", content=text))
            self._history[user_id].append(Message(role="assistant", content=response.content))

            content = response.content
            
            # ── Hallucination Mitigation: Strip Markdown Image Links ──
            # The AI sometimes hallucinations fake URLs like ![chart](https://placeholder...)
            content = re.sub(r"!\[.*?\]\(.*?\)", "", content)
            
            # ── Handle Native ECharts JSON ──
            if "ECHART_JSON:" in content:
                try:
                    # Extract path from ECHART_JSON:/path/to/file.json
                    json_path = content.split("ECHART_JSON:")[-1].strip()
                    if os.path.exists(json_path):
                        with open(json_path) as f:
                            chart_data = json.loads(f.read())
                        
                        chart_title = chart_data.get("title", {}).get("text", "Native Chart")
                        # Phase 2: Convert to PNG via bridge
                        from seahorse_ai.tools.viz import render_echarts_to_png
                        
                        png_path = await render_echarts_to_png(json.dumps(chart_data))
                        if png_path:
                            # Attach to response so the standard image-sending logic picks it up
                            if not hasattr(response, "image_paths"):
                                response.image_paths = []
                            response.image_paths.append(png_path)
                            content = f"📊 **Chart Generated**: {chart_title}"
                        else:
                            content = f"📊 **[PRO NATIVE CHART]**: {chart_title}\n\n"
                            content += "*(Rendering failed, showing as fallback text)*"
                except Exception as e:
                    logger.error("Telegram: Failed to parse native echart json: %s", e)

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
                                logger.warning(
                                    "Telegram: Photo caption Markdown failed, falling back"
                                )
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
                                parse_mode=ParseMode.MARKDOWN,
                            )
                        return

            await self._safe_send_message(
                context, chat_id, content, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.exception("Error processing Telegram input in %s:", agent_id)
            clean_error = _escape_markdown(str(e).split(":")[0])
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ ผมพบปัญหาขัดข้องชั่วคราว: {clean_error}"
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
                context, chat_id, f"_{choice}_", parse_mode=ParseMode.MARKDOWN
            )

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

    adapter = TelegramAdapter(
        router_url=os.environ.get("SEAHORSE_ROUTER_URL", "http://localhost:8000")
    )

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
        fast_path_model=os.environ.get(
            "SEAHORSE_FAST_PATH_MODEL", "openrouter/google/gemini-3.1-flash-lite-preview"
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
    app.add_handler(CommandHandler("stats", adapter.stats_command))
    app.add_handler(CommandHandler("remember", adapter.remember_command))
    app.add_handler(CommandHandler("search", adapter.search_command))
    app.add_handler(CommandHandler("reflect", adapter.reflect_command))

    app.add_handler(MessageHandler(filters.ALL, adapter.handle_message))

    app.add_handler(CallbackQueryHandler(adapter.handle_callback))

    # Optional Football Integration
    if os.environ.get("SEAHORSE_ENABLE_FOOTBALL") == "true":
        logger.info("Telegram: Football integration enabled. Starting background tasks...")
        import asyncio
        from seahorse_ai.analysis.football_eval import init_eval_db, resolve_pending_predictions
        from seahorse_ai.analysis.watcher import AnomalyWatcher

        watcher = AnomalyWatcher(llm_backend=router)
        watcher._notify = adapter.send_proactive_alert

        async def post_init(application: any) -> None:
            interval = int(os.environ.get("SEAHORSE_ALERTS_INTERVAL", "300"))
            asyncio.create_task(watcher.start(interval_seconds=interval))
            asyncio.create_task(init_eval_db())
            
            # Phase 2: Result Collector Task (runs every 1 hour)
            async def result_collector_loop():
                while True:
                    try:
                        await resolve_pending_predictions()
                    except Exception as e:
                        logger.error(f"Telegram: Result collector loop error: {e}")
                    await asyncio.sleep(3600)
            
            asyncio.create_task(result_collector_loop())
            logger.info("Telegram: AnomalyWatcher, FootballEval, and ResultCollector tasks started.")

        app.post_init = post_init
    else:
        logger.info("Telegram: Football integration disabled.")

    logger.info("Telegram bot starting via run_polling...")

    app.run_polling(
        allowed_updates=[
            "message",
            "channel_post",
            "callback_query",
            "edited_message",
            "edited_channel_post",
        ],
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
