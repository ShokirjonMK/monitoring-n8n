"""Anthropic Claude integration."""
import json
import logging
from typing import AsyncIterator
import anthropic

log = logging.getLogger("hub.ai")


def get_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def chat_once(api_key: str, model: str, system: str, messages: list[dict],
              context: dict | None = None) -> str:
    """One-shot chat. messages: [{role, content}, ...] in Anthropic format."""
    client = get_client(api_key)

    msgs = list(messages)
    if context:
        # Inject server context into the user's last message, so Claude sees the data.
        ctx_str = "<server_context>\n" + json.dumps(context, indent=2)[:30000] + "\n</server_context>"
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = {**msgs[-1], "content": ctx_str + "\n\n" + msgs[-1]["content"]}

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=msgs,
        )
        return resp.content[0].text if resp.content else ""
    except Exception as e:
        log.error(f"AI error: {e}")
        return f"❌ AI xato: {e}"


def summarize_status(api_key: str, model: str, system: str, status_payload: list[dict]) -> str:
    """Ask Claude for a one-paragraph summary of fleet health."""
    prompt = (
        "Quyidagi serverlar holatini analiz qil va qisqacha (5 jumladan ortiq emas) xulosa ber. "
        "Anomaliya yoki diqqat talab qiluvchi narsalarni alohida belgila."
    )
    return chat_once(
        api_key, model, system,
        messages=[{"role": "user", "content": prompt}],
        context={"servers": status_payload},
    )
