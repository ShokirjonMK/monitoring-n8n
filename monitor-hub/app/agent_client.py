"""Talks to monitor-agent instances over HTTP."""
import asyncio
import logging
from typing import Any
import httpx

log = logging.getLogger("hub.agent")


async def _request(method: str, base_url: str, token: str, path: str, **kw) -> dict | None:
    url = base_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}"}
    timeout = kw.pop("timeout", 20)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(method, url, headers=headers, **kw)
        if r.status_code >= 400:
            log.warning(f"{method} {url} → {r.status_code} {r.text[:200]}")
            return {"_error": f"HTTP {r.status_code}", "_body": r.text[:300]}
        try:
            return r.json()
        except Exception:
            return {"_error": "not-json", "_body": r.text[:300]}
    except Exception as e:
        log.error(f"{method} {url} → {e}")
        return {"_error": str(e)[:300]}


async def health(base_url: str) -> dict | None:
    """Public — no auth needed."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(base_url.rstrip("/") + "/health")
            return r.json() if r.status_code == 200 else {"_error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"_error": str(e)[:200]}


async def status(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/status", timeout=30) or {}


async def containers(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/containers", timeout=15) or {}


async def resources(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/resources", timeout=10) or {}


async def endpoints(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/endpoints", timeout=20) or {}


async def databases(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/databases", timeout=20) or {}


async def ssl_all(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/ssl/all", timeout=60) or {}


async def ssl_one(base_url: str, token: str, host: str, port: int = 443) -> dict:
    return await _request("GET", base_url, token, f"/ssl?host={host}&port={port}") or {}


async def backup_list(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/backup/list", timeout=10) or {}


async def backup_run(base_url: str, token: str) -> dict:
    return await _request("POST", base_url, token, "/backup/run", timeout=600) or {}


async def get_config(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/config", timeout=10) or {}


async def reload_config(base_url: str, token: str) -> dict:
    return await _request("POST", base_url, token, "/reload", timeout=10) or {}


# ─── Swarm ────────────────────────────────────────────────────────────────────

async def swarm_info(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/swarm/info", timeout=10) or {}


async def swarm_services(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/swarm/services", timeout=20) or {}


async def swarm_nodes(base_url: str, token: str) -> dict:
    return await _request("GET", base_url, token, "/swarm/nodes", timeout=15) or {}


async def swarm_service_metrics(base_url: str, token: str, service: str) -> dict:
    return await _request("GET", base_url, token, f"/swarm/service/{service}/metrics", timeout=20) or {}


async def swarm_scale(base_url: str, token: str, service: str, replicas: int) -> dict:
    return await _request("POST", base_url, token,
                          f"/swarm/service/{service}/scale?replicas={replicas}",
                          timeout=60) or {}


async def gather_all_status(servers: list[dict]) -> list[dict]:
    """Concurrently fetch /status from every active server."""
    async def one(s):
        if not s.get("is_active"):
            return {"server": s, "status": None, "error": "inactive"}
        result = await status(s["base_url"], s["agent_token"])
        return {"server": s, "status": result}
    return await asyncio.gather(*[one(s) for s in servers])
