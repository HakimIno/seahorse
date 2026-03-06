"""seahorse_ai.tools.integrations — External integrations for Slack and Google Calendar.

Requires environment variables:
- SLACK_BOT_TOKEN
- GOOGLE_APPLICATION_CREDENTIALS (JSON path)
"""
from __future__ import annotations

import logging
import os

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# ── Slack ─────────────────────────────────────────────────────────────────────

@tool(
    "Send a message to a Slack channel. "
    "Requires SLACK_BOT_TOKEN in environment. "
    "Input: channel (e.g., '#general' or 'C12345'), text (the message content)."
)
async def slack_send_message(channel: str, text: str) -> str:
    """Send a message to a Slack channel."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return "Error: SLACK_BOT_TOKEN not found in environment."
        
    try:
        from slack_sdk.web.async_client import AsyncWebClient
        client = AsyncWebClient(token=token)
        response = await client.chat_postMessage(channel=channel, text=text)
        if response["ok"]:
            return f"Successfully sent Slack message to {channel}."
        return f"Error sending Slack message: {response['error']}"
    except Exception as exc:
        logger.error("Slack integration failed: %s", exc)
        return f"Error: {exc}"

# ── Google Calendar ───────────────────────────────────────────────────────────

@tool(
    "Add an event to Google Calendar. "
    "Requires GOOGLE_APPLICATION_CREDENTIALS in environment. "
    "Input: summary, start_time (ISO), end_time (ISO), description (optional)."
)
async def google_calendar_add_event(
    summary: str, start_time: str, end_time: str, description: str = ""
) -> str:
    """Add a new event to the primary Google Calendar."""
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        return "Error: GOOGLE_APPLICATION_CREDENTIALS not found in environment."

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time, 'timeZone': 'UTC'},
        }
        
        import asyncio
        loop = asyncio.get_running_loop()
        func = lambda: service.events().insert(calendarId='primary', body=event).execute()
        created_event = await loop.run_in_executor(None, func)
        
        return f"Successfully created event: {created_event.get('htmlLink')}"
    except Exception as exc:
        logger.error("Google Calendar integration failed: %s", exc)
        return f"Error: {exc}"
