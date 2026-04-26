"""
Telegram notifier — admin-panel managed defaults + per-server overrides.

Resolution order for `resolve_alert_channel(server)`:
  1. server.alert_bot_token + server.alert_chat_id  (per-server override)
  2. HubSettings.telegram_bot_token + HubSettings.alert_chat_id  (admin panel)
  3. HubSettings.telegram_bot_token + HubSettings.default_chat_id  (admin panel)
  4. env TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID  (.env override)
  5. env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  (last-ditch)

Same idea for reports (alert_* → report_*).
"""
from __future__ import annotations

import os
import logging
from typing import Optional
import httpx
from sqlmodel import Session, select

from . import db as DB

log = logging.getLogger("hub.notify")

ENV_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
ENV_DEFAULT_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
ENV_ALERT_CHAT = os.getenv("TELEGRAM_ALERT_CHAT_ID", "") or ENV_DEFAULT_CHAT
ENV_REPORT_CHAT = os.getenv("TELEGRAM_REPORT_CHAT_ID", "") or ENV_DEFAULT_CHAT


class Channel:
    """A (bot_token, chat_id) pair with a label."""
    def __init__(self, bot_token: str, chat_id: str, label: str = ""):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id else ""
        self.label = label

    @property
    def ok(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @property
    def bot_id(self) -> str:
        return self.bot_token.split(":")[0] if self.bot_token else ""

    def __repr__(self):
        return f"Channel({self.label}, bot={self.bot_id}, chat={self.chat_id})"


def _hub() -> Optional[DB.HubSettings]:
    try:
        with Session(DB.engine) as s:
            return s.exec(select(DB.HubSettings).where(DB.HubSettings.id == 1)).first()
    except Exception as e:
        log.warning(f"hub settings fetch failed: {e}")
        return None


def resolve_alert_channel(server: Optional[DB.Server] = None) -> Channel:
    h = _hub()
    db_token = (h.telegram_bot_token if h else None) or ENV_BOT
    db_alert = (h.alert_chat_id if h else None) or (h.default_chat_id if h else None) \
               or ENV_ALERT_CHAT

    if server and server.alert_bot_token and server.alert_chat_id:
        return Channel(server.alert_bot_token, server.alert_chat_id, "server-alert")
    return Channel(db_token, db_alert, "default-alert")


def resolve_report_channel(server: Optional[DB.Server] = None) -> Channel:
    h = _hub()
    db_token = (h.telegram_bot_token if h else None) or ENV_BOT
    db_report = (h.report_chat_id if h else None) or (h.default_chat_id if h else None) \
                or ENV_REPORT_CHAT

    if server and server.report_bot_token and server.report_chat_id:
        return Channel(server.report_bot_token, server.report_chat_id, "server-report")
    return Channel(db_token, db_report, "default-report")


async def send_message(channel: Channel, text: str, parse_mode: str = "HTML") -> dict:
    if not channel.ok:
        log.warning(f"channel not configured: {channel}")
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


# ─── Discovery helper (find chats the bot is in) ─────────────────────────────

async def discover_chats(bot_token: Optional[str] = None) -> list[dict]:
    """Call getUpdates and extract distinct chats the bot has interacted with."""
    token = bot_token or ENV_BOT
    h = _hub()
    if h and h.telegram_bot_token:
        token = h.telegram_bot_token
    if not token:
        return []
    url = f"https://api.telegram.org/bot{token}/getUpdates?allowed_updates=%5B%22message%22%2C%22channel_post%22%2C%22my_chat_member%22%5D"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
            j = r.json()
        if not j.get("ok"):
            return []
        seen = {}
        for upd in j.get("result", []):
            chat = (upd.get("my_chat_member") or {}).get("chat") \
                   or (upd.get("channel_post") or {}).get("chat") \
                   or (upd.get("message") or {}).get("chat")
            if chat and chat.get("id") not in seen:
                seen[chat["id"]] = {
                    "id": chat["id"],
                    "type": chat.get("type"),
                    "title": chat.get("title") or chat.get("first_name") or chat.get("username"),
                }
        return list(seen.values())
    except Exception as e:
        log.error(f"discover_chats failed: {e}")
        return []
