"""Anthropic Claude integration."""
import json
import logging
from typing import Any
import anthropic

log = logging.getLogger("hub.ai")


def get_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def validate_key(api_key: str, model: str = "claude-haiku-4-5-20251001") -> dict:
    """Quick check: cheap call to validate the key + model are usable."""
    if not api_key or not api_key.startswith("sk-ant-"):
        return {"ok": False, "error": "API kalit formati noto'g'ri (sk-ant-... bilan boshlanishi kerak)"}
    try:
        client = get_client(api_key)
        resp = client.messages.create(
            model=model, max_tokens=20,
            messages=[{"role": "user", "content": "Reply with just 'ok'"}],
        )
        text = resp.content[0].text if resp.content else ""
        return {"ok": True, "model": model, "reply": text[:50]}
    except anthropic.AuthenticationError as e:
        return {"ok": False, "error": f"Auth xato: kalit noto'g'ri yoki tugagan ({e.message[:80]})"}
    except anthropic.NotFoundError as e:
        return {"ok": False, "error": f"Model topilmadi: {model}"}
    except anthropic.APIError as e:
        return {"ok": False, "error": f"API xato: {str(e)[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


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


def explain_server(api_key: str, model: str, system: str, server_status: dict) -> str:
    """Detailed analysis of one server."""
    prompt = (
        "Quyidagi server holatini batafsil tahlil qil. "
        "1) umumiy baho (yashil/sariq/qizil); "
        "2) muammoli komponentlar bo'lsa — nima va nima sababdan; "
        "3) tavsiya qilinadigan amallar (aniq buyruqlar bilan); "
        "4) keyingi 24 soatda nimani kuzatish kerak. "
        "Markdown formatda, qisqa va aniq."
    )
    return chat_once(
        api_key, model, system,
        messages=[{"role": "user", "content": prompt}],
        context={"server": server_status},
    )


def suggest_fix(api_key: str, model: str, system: str, alert: dict, server_status: dict | None = None) -> str:
    """Given an alert, suggest concrete commands and steps."""
    prompt = (
        "Quyidagi alert ko'rsatildi. Bu nima muammo, qanday tuzatish mumkin? "
        "Aniq SSH/docker buyruqlari ber. Markdown formatda, ortiqcha so'z yo'q. "
        "Diagnostika qilish ketma-ketligini list ko'rinishida yoz."
    )
    ctx = {"alert": alert}
    if server_status:
        ctx["server_now"] = server_status
    return chat_once(
        api_key, model, system,
        messages=[{"role": "user", "content": prompt}],
        context=ctx,
    )


def smart_digest(api_key: str, model: str, system: str, server_status: dict, recent_alerts: list[dict]) -> str:
    """AI-written daily digest (replaces the templated one)."""
    prompt = (
        "Server uchun kunlik hisobotni yoz. Telegram'da ko'rinadi (HTML). "
        "Quyidagicha tuzilish: emoji bilan sarlavha, 3-5 jumlada xulosa, "
        "ro'yxatda muhim metrikalar (containerlar, endpointlar, bazalar, disk, RAM, load). "
        "Agar muammo yoki anomaliya bo'lsa — alohida 'Diqqat' bo'limi. "
        "Maksimal 1500 belgi. <b>, <i>, <code> teglardan foydalan. Markdown EMAS."
    )
    return chat_once(
        api_key, model, system,
        messages=[{"role": "user", "content": prompt}],
        context={"server": server_status, "recent_alerts_24h": recent_alerts},
    )


def analyze_logs(api_key: str, model: str, system: str, logs: str, context: str = "") -> str:
    """User pastes logs, AI summarizes and identifies issues."""
    prompt = (
        "Quyidagi loglarni tahlil qil va: 1) qanday xatolar bor; 2) nima sababdan bo'lishi mumkin; "
        "3) keyingi qadamlar — aniq buyruqlar bilan."
    )
    if context:
        prompt += f"\nKontekst: {context}"
    return chat_once(
        api_key, model, system,
        messages=[{"role": "user", "content": prompt}],
        context={"logs": logs[:20000]},
    )
