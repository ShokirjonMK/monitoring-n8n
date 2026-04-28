"""AI integration — multi-provider via app.providers, with compact context."""
import json
import logging
import datetime
from typing import Any
from . import providers as P

log = logging.getLogger("hub.ai")


# Per-provider rough TPM/context budgets (in tokens). Conservative — keep ~30%
# headroom for the system prompt + completion.
PROVIDER_INPUT_BUDGET = {
    # Groq free tier: 12K TPM for llama-3.3-70b — keep 7K input budget
    "groq":         7_000,
    "cerebras":     7_000,
    # OpenRouter free models are highly variable — assume modest
    "openrouter":   8_000,
    # Gemini Flash has 1M context but free RPD limit; keep 30K
    "gemini":      30_000,
    # Anthropic Claude — paid, 200K context. Plenty of headroom.
    "anthropic":   60_000,
    # OpenAI gpt-4o family — 128K context.
    "openai":      40_000,
    "deepseek":    20_000,
    "custom":       8_000,
}


def _est_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token in english/russian, ~3.5 in Uzbek/JSON."""
    return max(1, len(text) // 4)


def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date, datetime.time)):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


# ─── Compact text representations (10x smaller than JSON) ────────────────────

def _compact_server(name: str, st: dict, recent_alerts: list[dict] = None) -> str:
    """One-line + bullet issues version of a server status."""
    if not st or "_error" in (st or {}):
        return f"[{name}] DOWN: {(st or {}).get('_error', 'no response')[:120]}"

    containers = st.get("containers") or []
    eps = st.get("endpoints") or []
    dbs = st.get("databases") or []
    disk = next((d for d in (st.get("disk") or []) if d.get("mount") in ("/host", "/")),
                (st.get("disk") or [{}])[0] if st.get("disk") else {})
    mem = st.get("memory") or {}
    load = st.get("load") or {}

    healthy_c = sum(1 for c in containers
                    if c.get("state") == "running" and c.get("health") in ("healthy", "none"))
    bad_c = [c.get("name", "?") for c in containers
             if c.get("state") != "running" or c.get("health") == "unhealthy"]
    bad_e = [(e.get("name", "?"), e.get("status") or "ERR") for e in eps if not e.get("ok")]
    bad_d = [(d.get("name", "?"), (d.get("error") or "down")[:60]) for d in dbs if not d.get("ok")]

    uptime_d = (st.get("uptime_seconds") or 0) // 86400

    line = (
        f"[{name}] uptime={uptime_d}d "
        f"containers={healthy_c}/{len(containers)} "
        f"endpoints={sum(1 for e in eps if e.get('ok'))}/{len(eps)} "
        f"dbs={sum(1 for d in dbs if d.get('ok'))}/{len(dbs)} "
        f"disk={disk.get('used_pct', 0)}% "
        f"ram={mem.get('used_pct', 0)}% "
        f"load={load.get('1m', 0)}"
    )

    issues = []
    if bad_c: issues.append(f"unhealthy_containers: {', '.join(bad_c[:6])}")
    if bad_e: issues.append("failed_endpoints: " + ", ".join(f"{n}({s})" for n, s in bad_e[:6]))
    if bad_d: issues.append("failed_dbs: " + ", ".join(f"{n}({e[:50]})" for n, e in bad_d[:6]))

    if recent_alerts:
        open_alerts = [a for a in recent_alerts if not a.get("resolved")]
        if open_alerts:
            issues.append(f"open_alerts({len(open_alerts)}): " + ", ".join(
                f"{a.get('type')}::{a.get('key', '?').split('::')[-1]}"
                for a in open_alerts[:5]))

    if issues:
        line += "\n  " + "\n  ".join(issues)
    return line


def _compact_fleet(fleet: list[dict]) -> str:
    """fleet = [{server: {...}, status: {...}}, ...] — from gather_all_status."""
    lines = []
    for item in fleet:
        srv = item.get("server") or {}
        st = item.get("status") or {}
        lines.append(_compact_server(srv.get("name", "?"), st))
    return "\n".join(lines)


def _compact_alert(alert: dict) -> str:
    """One-line representation of an alert."""
    parts = [
        f"server={alert.get('server', '?')}",
        f"type={alert.get('type', '?')}",
        f"key={alert.get('key', '?')}",
        f"level={alert.get('level', '?')}",
    ]
    if alert.get("consecutive_count"):
        parts.append(f"count={alert['consecutive_count']}")
    msg = alert.get("message", "")
    if msg:
        # Strip HTML tags for compactness
        import re
        msg = re.sub(r"<[^>]+>", "", msg)[:200]
    return " ".join(parts) + (f"\n  msg: {msg}" if msg else "")


# ─── Context shrinker ────────────────────────────────────────────────────────

def _build_context(provider: str, payload: Any, max_tokens: int | None = None) -> str:
    """Build a context string for AI, sized to provider budget."""
    budget = max_tokens or PROVIDER_INPUT_BUDGET.get(provider, 8_000)
    # Reserve ~25% of budget for system prompt + completion + user message
    target_tokens = int(budget * 0.55)
    target_chars = target_tokens * 4

    # Try compact first (handle structured payloads)
    if isinstance(payload, dict):
        if "fleet" in payload:
            text = _compact_fleet(payload["fleet"])
        elif "server" in payload:
            srv = payload["server"]
            if isinstance(srv, dict):
                name = srv.get("name") or "server"
                st = srv.get("status") or srv
                recent = payload.get("recent_alerts") or payload.get("recent_alerts_24h") or []
                text = _compact_server(name, st, recent)
            else:
                text = json.dumps(payload, default=_json_default, indent=2)
        elif "alert" in payload:
            text = _compact_alert(payload["alert"])
            # Add server snapshot if present
            if "server_now" in payload and payload["server_now"]:
                text += "\n\nServer hozir:\n" + _compact_server(
                    payload.get("alert", {}).get("server", "?"),
                    payload["server_now"],
                )
        elif "logs" in payload:
            text = "Logs:\n" + (payload["logs"] or "")[:target_chars - 200]
        else:
            text = json.dumps(payload, default=_json_default, indent=2)
    else:
        text = json.dumps(payload, default=_json_default, indent=2)

    # Hard cap
    if len(text) > target_chars:
        text = text[:target_chars] + "\n... [truncated]"
    return text


def _approx_message_tokens(messages: list[dict], system: str) -> int:
    total = _est_tokens(system or "")
    for m in messages:
        total += _est_tokens(m.get("content", ""))
    return total


# ─── Public API ──────────────────────────────────────────────────────────────

def chat_once(api_key: str, model: str, system: str, messages: list[dict],
              context: dict | None = None,
              provider: str = "anthropic", base_url: str = "") -> str:
    """One-shot chat. messages: [{role, content}, ...]."""
    msgs = list(messages)
    if context:
        ctx_text = _build_context(provider, context)
        ctx_block = f"<context>\n{ctx_text}\n</context>"
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = {**msgs[-1], "content": ctx_block + "\n\n" + msgs[-1]["content"]}

    # Token estimation — log if we're near budget
    budget = PROVIDER_INPUT_BUDGET.get(provider, 8_000)
    est = _approx_message_tokens(msgs, system or "")
    if est > budget * 0.9:
        log.warning(f"AI context near limit: provider={provider} est={est} budget={budget}")

    try:
        return P.chat(provider, api_key, model, system, msgs, base_url=base_url)
    except P.ProviderError as e:
        msg = str(e)
        # Auto-shrink and retry once on 413
        if ("413" in msg or "too large" in msg.lower() or "TPM" in msg) and context:
            log.warning(f"AI 413 — shrinking context and retrying: {msg[:200]}")
            half_budget = max(1000, budget // 2)
            shrunk = _build_context(provider, context, max_tokens=half_budget)
            new_msgs = list(messages)
            if new_msgs and new_msgs[-1]["role"] == "user":
                new_msgs[-1] = {**new_msgs[-1],
                                "content": f"<context>\n{shrunk}\n</context>\n\n" + new_msgs[-1]["content"]}
            try:
                return P.chat(provider, api_key, model, system, new_msgs, base_url=base_url)
            except P.ProviderError as e2:
                log.error(f"AI retry failed: {e2}")
                return f"❌ AI xato ({provider}): {e2}"
        log.error(f"AI provider error ({provider}): {e}")
        return f"❌ AI xato ({provider}): {e}"
    except Exception as e:
        log.error(f"AI error: {e}")
        return f"❌ AI xato: {e}"


def validate_key(api_key: str, model: str, provider: str = "anthropic", base_url: str = "") -> dict:
    return P.validate(provider, api_key, model, base_url=base_url)


def summarize_status(api_key: str, model: str, system: str, status_payload: list[dict],
                     provider: str = "anthropic", base_url: str = "") -> str:
    prompt = (
        "Quyidagi serverlar holatini analiz qil va qisqacha (5 jumladan ortiq emas) xulosa ber. "
        "Anomaliya yoki diqqat talab qiluvchi narsalarni alohida belgila."
    )
    return chat_once(api_key, model, system,
                     messages=[{"role": "user", "content": prompt}],
                     context={"fleet": status_payload},
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
                     context={"logs": logs},
                     provider=provider, base_url=base_url)
