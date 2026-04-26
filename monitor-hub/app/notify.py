"""
Telegram notifier with per-server channel routing.

Resolution order for `send_alert(server)`:
  1. server.alert_bot_token + server.alert_chat_id (if both set)
  2. TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID env (if alert chat exists)
  3. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env (universal default)

Same for `send_report` but with report_* fields.
"""
from __future__ import annotations

import os
import logging
from typing import Optional
import httpx

from . import db as DB

log = logging.getLogger("hub.notify")

DEFAULT_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
DEFAULT_ALERT_CHAT = os.getenv("TELEGRAM_ALERT_CHAT_ID", "") or DEFAULT_CHAT
DEFAULT_REPORT_CHAT = os.getenv("TELEGRAM_REPORT_CHAT_ID", "") or DEFAULT_CHAT


class Channel:
    """A (bot_token, chat_id) pair to send to."""
    def __init__(self, bot_token: str, chat_id: str, label: str = ""):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id else ""
        self.label = label

    @property
    def ok(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @property
    def bot_id(self) -> str:
        # First part of token before colon, public-safe identifier
        return self.bot_token.split(":")[0] if self.bot_token else ""


def resolve_alert_channel(server: Optional[DB.Server] = None) -> Channel:
    if server and server.alert_bot_token and server.alert_chat_id:
        return Channel(server.alert_bot_token, server.alert_chat_id, "server-alert")
    return Channel(DEFAULT_BOT, DEFAULT_ALERT_CHAT, "default-alert")


def resolve_report_channel(server: Optional[DB.Server] = None) -> Channel:
    if server and server.report_bot_token and server.report_chat_id:
        return Channel(server.report_bot_token, server.report_chat_id, "server-report")
    return Channel(DEFAULT_BOT, DEFAULT_REPORT_CHAT, "default-report")


async def send_message(channel: Channel, text: str, parse_mode: str = "HTML") -> dict:
    if not channel.ok:
        return {"ok": False, "error": "channel not configured"}

    url = f"https://api.telegram.org/bot{channel.bot_token}/sendMessage"
    payload = {
        "chat_id": channel.chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, data=payload)
            j = r.json()
            if not j.get("ok"):
                log.warning(f"Telegram error to {channel.chat_id}: {j}")
            return j
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return {"ok": False, "error": str(e)[:200]}


async def send_document(channel: Channel, filename: str, content: bytes,
                        caption: str = "") -> dict:
    if not channel.ok:
        return {"ok": False, "error": "channel not configured"}
    url = f"https://api.telegram.org/bot{channel.bot_token}/sendDocument"
    files = {"document": (filename, content)}
    data = {"chat_id": channel.chat_id, "caption": caption[:1024]}
    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(url, data=data, files=files)
            return r.json()
    except Exception as e:
        log.error(f"Telegram doc send failed: {e}")
        return {"ok": False, "error": str(e)[:200]}


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
