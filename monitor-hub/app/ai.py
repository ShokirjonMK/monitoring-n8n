"""AI integration — multi-provider via app.providers."""
import json
import logging
from . import providers as P

log = logging.getLogger("hub.ai")


def chat_once(api_key: str, model: str, system: str, messages: list[dict],
              context: dict | None = None,
              provider: str = "anthropic", base_url: str = "") -> str:
    """One-shot chat. messages: [{role, content}, ...]."""
    msgs = list(messages)
    if context:
        ctx_str = "<server_context>\n" + json.dumps(context, indent=2)[:30000] + "\n</server_context>"
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = {**msgs[-1], "content": ctx_str + "\n\n" + msgs[-1]["content"]}
    try:
        return P.chat(provider, api_key, model, system, msgs, base_url=base_url)
    except P.ProviderError as e:
        log.error(f"AI provider error ({provider}): {e}")
        return f"❌ AI xato ({provider}): {e}"
    except Exception as e:
        log.error(f"AI error: {e}")
        return f"❌ AI xato: {e}"


def validate_key(api_key: str, model: str, provider: str = "anthropic", base_url: str = "") -> dict:
    """Validate provider+model+key combination."""
    return P.validate(provider, api_key, model, base_url=base_url)


def summarize_status(api_key: str, model: str, system: str, status_payload: list[dict],
                     provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Quyidagi serverlar holatini analiz qil va qisqacha (5 jumladan ortiq emas) xulosa ber. "
        "Anomaliya yoki diqqat talab qiluvchi narsalarni alohida belgila."
    )
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context={"servers": status_payload},
                     provider=provider, base_url=base_url)


def explain_server(api_key: str, model: str, system: str, server_status: dict,
                   provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Quyidagi server holatini batafsil tahlil qil. "
        "1) umumiy baho (yashil/sariq/qizil); "
        "2) muammoli komponentlar bo'lsa — nima va nima sababdan; "
        "3) tavsiya qilinadigan amallar (aniq buyruqlar bilan); "
        "4) keyingi 24 soatda nimani kuzatish kerak. "
        "Markdown formatda, qisqa va aniq."
    )
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context={"server": server_status},
                     provider=provider, base_url=base_url)


def suggest_fix(api_key: str, model: str, system: str, alert: dict,
                server_status: dict | None = None,
                provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Quyidagi alert ko'rsatildi. Bu nima muammo, qanday tuzatish mumkin? "
        "Aniq SSH/docker buyruqlari ber. Markdown formatda, ortiqcha so'z yo'q. "
        "Diagnostika qilish ketma-ketligini list ko'rinishida yoz."
    )
    ctx = {"alert": alert}
    if server_status:
        ctx["server_now"] = server_status
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context=ctx,
                     provider=provider, base_url=base_url)


def smart_digest(api_key: str, model: str, system: str, server_status: dict,
                 recent_alerts: list[dict],
                 provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Server uchun kunlik hisobotni yoz. Telegram'da ko'rinadi (HTML). "
        "Quyidagicha tuzilish: emoji bilan sarlavha, 3-5 jumlada xulosa, "
        "ro'yxatda muhim metrikalar (containerlar, endpointlar, bazalar, disk, RAM, load). "
        "Agar muammo yoki anomaliya bo'lsa — alohida 'Diqqat' bo'limi. "
        "Maksimal 1500 belgi. <b>, <i>, <code> teglardan foydalan. Markdown EMAS."
    )
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context={"server": server_status, "recent_alerts_24h": recent_alerts},
                     provider=provider, base_url=base_url)


def analyze_logs(api_key: str, model: str, system: str, logs: str, context: str = "",
                 provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Quyidagi loglarni tahlil qil va: 1) qanday xatolar bor; 2) nima sababdan bo'lishi mumkin; "
        "3) keyingi qadamlar — aniq buyruqlar bilan."
    )
    if context:
        prompt += f"\nKontekst: {context}"
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context={"logs": logs[:20000]},
                     provider=provider, base_url=base_url)
