"""
Multi-provider AI integration. Unified `chat()` interface across:

  - Anthropic Claude         (paid)
  - Google Gemini            (FREE, 1500/day)
  - Groq                     (FREE, 30 RPM)
  - OpenRouter               (FREE :free models)
  - Cerebras                 (FREE, fast)
  - OpenAI                   (paid)
  - DeepSeek                 (cheap)
  - Custom (OpenAI-compatible base_url)

We use httpx directly — no provider SDKs — so adding a new provider is just a
config entry in PROVIDERS below.

OpenAI-compatible providers (Groq/OpenRouter/OpenAI/Cerebras/DeepSeek/Custom)
share one adapter. Gemini and Anthropic have native protocols.
"""
from __future__ import annotations

import json
import logging
from typing import Any
import httpx

log = logging.getLogger("hub.providers")

# ─── Provider catalog ────────────────────────────────────────────────────────
# Each entry: name → {label, type, base_url, key_url, models, notes}

PROVIDERS = {
    "gemini": {
        "label": "Google Gemini  (BEPUL — 1500 req/kun)",
        "type": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_url": "https://aistudio.google.com/apikey",
        "free_tier": True,
        "models": [
            ("gemini-2.0-flash-exp", "Gemini 2.0 Flash (eng yangi, BEPUL)"),
            ("gemini-1.5-flash-latest", "Gemini 1.5 Flash (BEPUL, tez)"),
            ("gemini-1.5-flash-8b-latest", "Gemini 1.5 Flash 8B (BEPUL, eng tez)"),
            ("gemini-1.5-pro-latest", "Gemini 1.5 Pro (BEPUL, sifatli)"),
        ],
        "notes": "1500 so'rov/kun, 15 so'rov/daqiqa BEPUL. Google akkaunt kerak.",
    },
    "groq": {
        "label": "Groq  (BEPUL — eng tez Llama)",
        "type": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "https://console.groq.com/keys",
        "free_tier": True,
        "models": [
            ("llama-3.3-70b-versatile", "Llama 3.3 70B (eng yaxshi BEPUL)"),
            ("llama-3.1-70b-versatile", "Llama 3.1 70B (BEPUL)"),
            ("llama-3.1-8b-instant", "Llama 3.1 8B (eng tez)"),
            ("mixtral-8x7b-32768", "Mixtral 8x7B (uzun kontekst)"),
            ("gemma2-9b-it", "Gemma 2 9B"),
        ],
        "notes": "30 so'rov/daqiqa, 14400 token/daqiqa BEPUL. Eng tez inference.",
    },
    "openrouter": {
        "label": "OpenRouter  (BEPUL :free modellari)",
        "type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "https://openrouter.ai/keys",
        "free_tier": True,
        "models": [
            ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B :free"),
            ("google/gemini-2.0-flash-exp:free", "Gemini 2.0 Flash :free"),
            ("google/gemma-2-9b-it:free", "Gemma 2 9B :free"),
            ("qwen/qwen-2.5-72b-instruct:free", "Qwen 2.5 72B :free"),
            ("microsoft/phi-3-medium-128k-instruct:free", "Phi-3 Medium :free"),
            ("mistralai/mistral-7b-instruct:free", "Mistral 7B :free"),
            ("nousresearch/hermes-3-llama-3.1-405b:free", "Hermes 3 405B :free"),
        ],
        "notes": "Faqat ':free' qo'shimchasi bilan tugagan modellar BEPUL. Daily limits qo'llaniladi.",
    },
    "cerebras": {
        "label": "Cerebras  (BEPUL — super tez)",
        "type": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "key_url": "https://cloud.cerebras.ai/platform",
        "free_tier": True,
        "models": [
            ("llama-3.3-70b", "Llama 3.3 70B (eng yangi BEPUL)"),
            ("llama3.1-70b", "Llama 3.1 70B (BEPUL)"),
            ("llama3.1-8b", "Llama 3.1 8B (eng tez)"),
        ],
        "notes": "30 so'rov/daqiqa BEPUL. Dunyodagi eng tez LLM inference.",
    },
    "anthropic": {
        "label": "Anthropic Claude  (PULLIK)",
        "type": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "key_url": "https://console.anthropic.com/settings/keys",
        "free_tier": False,
        "models": [
            ("claude-opus-4-7", "Claude Opus 4.7 (eng kuchli)"),
            ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
            ("claude-haiku-4-5-20251001", "Claude Haiku 4.5 (tez)"),
        ],
        "notes": "Pullik. Yuqori sifat, lekin har so'rov uchun to'lov.",
    },
    "openai": {
        "label": "OpenAI  (PULLIK)",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "key_url": "https://platform.openai.com/api-keys",
        "free_tier": False,
        "models": [
            ("gpt-4o-mini", "GPT-4o mini (arzon)"),
            ("gpt-4o", "GPT-4o"),
            ("o1-mini", "o1-mini (reasoning)"),
        ],
        "notes": "Pullik. Yangi akkauntlarda ba'zan kichik free credit beriladi.",
    },
    "deepseek": {
        "label": "DeepSeek  (juda arzon)",
        "type": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "key_url": "https://platform.deepseek.com/api_keys",
        "free_tier": False,
        "models": [
            ("deepseek-chat", "DeepSeek-V3 (chat)"),
            ("deepseek-reasoner", "DeepSeek-R1 (reasoning)"),
        ],
        "notes": "Juda arzon (taxminan $0.14/M token). Pulli, lekin Anthropic'dan 100x arzonroq.",
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "type": "openai",
        "base_url": "",
        "key_url": "",
        "free_tier": False,
        "models": [],
        "notes": "Har qanday OpenAI-compatible endpoint (Ollama, LM Studio, custom). Base URL kiriting.",
    },
}


# ─── Adapters ────────────────────────────────────────────────────────────────

class ProviderError(Exception):
    pass


def _openai_chat(base_url: str, api_key: str, model: str,
                 system: str, messages: list[dict], max_tokens: int = 2048,
                 timeout: int = 60) -> str:
    """OpenAI-compatible /chat/completions call. Works for OpenAI, Groq,
    OpenRouter, Cerebras, DeepSeek, custom."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload_msgs = []
    if system:
        payload_msgs.append({"role": "system", "content": system})
    payload_msgs.extend(messages)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # OpenRouter wants identification headers
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://github.com/ShokirjonMK/monitoring-n8n"
        headers["X-Title"] = "Monitor Hub"

    body = {"model": model, "messages": payload_msgs, "max_tokens": max_tokens, "temperature": 0.3}
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"empty response: {str(data)[:200]}")
        return choices[0].get("message", {}).get("content", "")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        raise ProviderError(f"HTTP {e.response.status_code}: {body}")
    except Exception as e:
        raise ProviderError(str(e)[:300])


def _gemini_chat(api_key: str, model: str, system: str, messages: list[dict],
                 max_tokens: int = 2048, timeout: int = 60) -> str:
    """Google Gemini /generateContent call."""
    base = "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base}/models/{model}:generateContent?key={api_key}"

    # Gemini wants role: user/model and 'parts: [{text: ...}]'
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    body = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            # Could be safety-blocked
            raise ProviderError(f"no candidates: {str(data)[:300]}")
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        raise ProviderError(f"HTTP {e.response.status_code}: {body}")
    except Exception as e:
        raise ProviderError(str(e)[:300])


def _anthropic_chat(api_key: str, model: str, system: str, messages: list[dict],
                    max_tokens: int = 2048, timeout: int = 60) -> str:
    """Anthropic /messages call."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        body["system"] = system

    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        content = data.get("content") or []
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        raise ProviderError(f"HTTP {e.response.status_code}: {body}")
    except Exception as e:
        raise ProviderError(str(e)[:300])


# ─── Public API ──────────────────────────────────────────────────────────────

def chat(provider: str, api_key: str, model: str, system: str, messages: list[dict],
         max_tokens: int = 2048, base_url: str = "") -> str:
    """Dispatch to the right adapter based on provider name.

    Args:
      provider: key from PROVIDERS dict
      api_key: provider API key
      model: model name (provider-specific)
      system: system prompt
      messages: [{role: 'user'|'assistant', content: '...'}, ...]
      max_tokens: output cap
      base_url: override (only used for 'custom')

    Returns: assistant message text. Raises ProviderError on failure.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ProviderError(f"unknown provider: {provider}")

    if cfg["type"] == "anthropic":
        return _anthropic_chat(api_key, model, system, messages, max_tokens)
    if cfg["type"] == "gemini":
        return _gemini_chat(api_key, model, system, messages, max_tokens)
    if cfg["type"] == "openai":
        url = base_url.rstrip("/") if (provider == "custom" and base_url) else cfg["base_url"]
        if not url:
            raise ProviderError("custom provider requires base_url")
        return _openai_chat(url, api_key, model, system, messages, max_tokens)
    raise ProviderError(f"unsupported type: {cfg['type']}")


def validate(provider: str, api_key: str, model: str, base_url: str = "") -> dict:
    """Cheap validation call. Returns {ok, model, reply, error}."""
    if not api_key:
        return {"ok": False, "error": "API kalit kiritilmagan"}
    try:
        reply = chat(
            provider, api_key, model,
            system="Reply with just the word 'ok' and nothing else.",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=20, base_url=base_url,
        )
        return {"ok": True, "model": model, "reply": (reply or "")[:80]}
    except ProviderError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def list_providers() -> list[dict]:
    """For UI dropdown."""
    return [
        {"key": k, "label": v["label"], "free": v["free_tier"], "key_url": v["key_url"],
         "notes": v["notes"], "models": v["models"], "is_custom": k == "custom"}
        for k, v in PROVIDERS.items()
    ]
