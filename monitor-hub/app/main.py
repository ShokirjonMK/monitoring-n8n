"""monitor-hub — universal admin panel for the server fleet."""
from __future__ import annotations

import os
import json
import time
import logging
import datetime
import secrets
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select

from . import db as DB
from . import agent_client as AGENT
from . import ai as AI
from . import notify as NOTIFY
from .scheduler import scheduler

# ─── Setup ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("hub")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
SECRET = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)

app = FastAPI(title="monitor-hub", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=86400 * 7, same_site="lax")
app.mount("/static", StaticFiles(directory="/app/app/static"), name="static")

templates = Jinja2Templates(directory="/app/app/templates")
templates.env.globals["now"] = lambda: datetime.datetime.utcnow()


@app.on_event("startup")
async def _startup():
    DB.init_db()
    if os.getenv("HUB_SCHEDULER_ENABLED", "true").lower() == "true":
        scheduler.start()
    log.info("monitor-hub started")


@app.on_event("shutdown")
async def _shutdown():
    await scheduler.stop()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def require_login(request: Request):
    if not request.session.get("user"):
        raise HTTPException(307, headers={"Location": "/login"})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if request.session.get("user"):
        return RedirectResponse("/", 302)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse("/", 302)
    return RedirectResponse("/login?error=1", 302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 302)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _servers_dict(session: Session) -> list[dict]:
    return [s.model_dump() for s in session.exec(select(DB.Server)).all()]


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        servers = _servers_dict(s)
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
    results = await AGENT.gather_all_status(servers)

    # Aggregate health for the cards
    cards = []
    for r in results:
        srv = r["server"]
        st = r["status"] or {}
        if not st or "_error" in st:
            cards.append({
                "server": srv, "ok": False,
                "error": (st or {}).get("_error", "no response"),
                "containers_total": 0, "containers_healthy": 0,
                "endpoints_total": 0, "endpoints_ok": 0,
                "dbs_total": 0, "dbs_ok": 0,
                "disk_pct": 0, "mem_pct": 0, "load_1m": 0,
                "uptime_seconds": 0,
            })
            continue
        containers = st.get("containers", [])
        eps = st.get("endpoints", [])
        dbs = st.get("databases", [])
        disk = next((d for d in st.get("disk", []) if d["mount"] in ("/host", "/")),
                    (st.get("disk") or [{}])[0])
        cards.append({
            "server": srv, "ok": True, "raw": st,
            "containers_total": len(containers),
            "containers_healthy": sum(1 for c in containers
                                      if c["state"] == "running" and c["health"] in ("healthy", "none")),
            "containers_bad": [c for c in containers
                               if c["state"] != "running" or c["health"] == "unhealthy"],
            "endpoints_total": len(eps),
            "endpoints_ok": sum(1 for e in eps if e["ok"]),
            "endpoints_bad": [e for e in eps if not e["ok"]],
            "dbs_total": len(dbs),
            "dbs_ok": sum(1 for d in dbs if d["ok"]),
            "dbs_bad": [d for d in dbs if not d["ok"]],
            "disk_pct": disk.get("used_pct", 0),
            "mem_pct": (st.get("memory", {}) or {}).get("used_pct", 0),
            "load_1m": (st.get("load", {}) or {}).get("1m", 0),
            "uptime_seconds": st.get("uptime_seconds", 0),
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "cards": cards,
        "ai_enabled": ai and ai.enabled and bool(ai.api_key),
    })


@app.get("/api/dashboard")
async def api_dashboard(_=Depends(require_login)):
    """JSON endpoint for live polling."""
    with Session(DB.engine) as s:
        servers = _servers_dict(s)
    return await AGENT.gather_all_status(servers)


# ─── Servers CRUD ─────────────────────────────────────────────────────────────

@app.get("/servers", response_class=HTMLResponse)
async def servers_list(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        items = s.exec(select(DB.Server).order_by(DB.Server.created_at)).all()
    # Probe health for each
    healths = {}
    for srv in items:
        h = await AGENT.health(srv.base_url)
        healths[srv.id] = h or {"_error": "?"}
    return templates.TemplateResponse("servers.html", {
        "request": request, "servers": items, "healths": healths,
    })


@app.get("/servers/new", response_class=HTMLResponse)
def server_new_form(request: Request, _=Depends(require_login)):
    return templates.TemplateResponse("server_form.html", {
        "request": request, "server": None, "error": None,
    })


@app.post("/servers/new")
async def server_create(
    request: Request,
    name: str = Form(...),
    base_url: str = Form(...),
    agent_token: str = Form(...),
    description: str = Form(""),
    is_active: str = Form("off"),
    alert_bot_token: str = Form(""),
    alert_chat_id: str = Form(""),
    report_bot_token: str = Form(""),
    report_chat_id: str = Form(""),
    _=Depends(require_login),
):
    with Session(DB.engine) as s:
        if s.exec(select(DB.Server).where(DB.Server.name == name)).first():
            return templates.TemplateResponse("server_form.html", {
                "request": request, "server": None,
                "error": f"'{name}' allaqachon mavjud",
                "form": {"name": name, "base_url": base_url, "agent_token": agent_token,
                         "description": description},
            })
        srv = DB.Server(
            name=name.strip(), base_url=base_url.strip().rstrip("/"),
            agent_token=agent_token.strip(),
            description=description.strip() or None,
            is_active=(is_active == "on"),
            alert_bot_token=alert_bot_token.strip() or None,
            alert_chat_id=alert_chat_id.strip() or None,
            report_bot_token=report_bot_token.strip() or None,
            report_chat_id=report_chat_id.strip() or None,
        )
        s.add(srv)
        s.commit()
    return RedirectResponse("/servers", 302)


@app.get("/servers/{sid}", response_class=HTMLResponse)
async def server_detail(sid: int, request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return RedirectResponse("/servers", 302)
    # Live status
    st = await AGENT.status(srv.base_url, srv.agent_token)
    cfg = await AGENT.get_config(srv.base_url, srv.agent_token)
    backups = await AGENT.backup_list(srv.base_url, srv.agent_token)
    return templates.TemplateResponse("server_detail.html", {
        "request": request, "server": srv, "status": st, "config": cfg, "backups": backups,
    })


@app.get("/servers/{sid}/edit", response_class=HTMLResponse)
def server_edit_form(sid: int, request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return RedirectResponse("/servers", 302)
    return templates.TemplateResponse("server_form.html", {
        "request": request, "server": srv, "error": None,
    })


@app.post("/servers/{sid}/edit")
def server_update(
    sid: int,
    request: Request,
    name: str = Form(...),
    base_url: str = Form(...),
    agent_token: str = Form(...),
    description: str = Form(""),
    is_active: str = Form("off"),
    alert_bot_token: str = Form(""),
    alert_chat_id: str = Form(""),
    report_bot_token: str = Form(""),
    report_chat_id: str = Form(""),
    maintenance_until: str = Form(""),
    _=Depends(require_login),
):
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return RedirectResponse("/servers", 302)
        srv.name = name.strip()
        srv.base_url = base_url.strip().rstrip("/")
        srv.agent_token = agent_token.strip()
        srv.description = description.strip() or None
        srv.is_active = (is_active == "on")
        srv.alert_bot_token = alert_bot_token.strip() or None
        srv.alert_chat_id = alert_chat_id.strip() or None
        srv.report_bot_token = report_bot_token.strip() or None
        srv.report_chat_id = report_chat_id.strip() or None
        # Maintenance: parse datetime-local input
        if maintenance_until.strip():
            try:
                srv.maintenance_until = datetime.datetime.fromisoformat(maintenance_until.strip())
            except Exception:
                pass
        else:
            srv.maintenance_until = None
        srv.updated_at = datetime.datetime.utcnow()
        s.add(srv); s.commit()
    return RedirectResponse(f"/servers/{sid}", 302)


@app.post("/servers/{sid}/test-channels")
async def server_test_channels(sid: int, _=Depends(require_login)):
    """Send a test message to both alert and report channels."""
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return JSONResponse({"error": "not found"}, status_code=404)
    alert_ch = NOTIFY.resolve_alert_channel(srv)
    report_ch = NOTIFY.resolve_report_channel(srv)
    a = await NOTIFY.send_message(alert_ch,
        f"🧪 <b>Test alert</b> — server <b>{srv.name}</b>\nKanal: <code>{alert_ch.label}</code>")
    r = await NOTIFY.send_message(report_ch,
        f"🧪 <b>Test report</b> — server <b>{srv.name}</b>\nKanal: <code>{report_ch.label}</code>")
    return {"alert": a, "report": r,
            "alert_channel": alert_ch.label, "report_channel": report_ch.label}


@app.post("/servers/{sid}/delete")
def server_delete(sid: int, _=Depends(require_login)):
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if srv:
            s.delete(srv); s.commit()
    return RedirectResponse("/servers", 302)


@app.post("/servers/{sid}/probe")
async def server_probe(sid: int, _=Depends(require_login)):
    """Manual /reload + /status check."""
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return JSONResponse({"error": "not found"}, status_code=404)
    h = await AGENT.health(srv.base_url)
    if h.get("status") != "ok":
        return JSONResponse({"ok": False, "health": h}, status_code=200)
    st = await AGENT.status(srv.base_url, srv.agent_token)
    return {"ok": True, "health": h, "status": st}


# ─── Backups ──────────────────────────────────────────────────────────────────

@app.get("/backups", response_class=HTMLResponse)
async def backups_list(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        servers = s.exec(select(DB.Server).where(DB.Server.is_active == True)).all()
    items = []
    for srv in servers:
        bl = await AGENT.backup_list(srv.base_url, srv.agent_token)
        for f in (bl.get("files") or []):
            items.append({"server": srv, **f})
    return templates.TemplateResponse("backups.html", {
        "request": request, "items": items, "servers": servers,
    })


@app.post("/backups/run/{sid}")
async def backup_run(sid: int, _=Depends(require_login)):
    with Session(DB.engine) as s:
        srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        if not srv:
            return JSONResponse({"error": "not found"}, status_code=404)
    return await AGENT.backup_run(srv.base_url, srv.agent_token)


# ─── SSL / Domains ────────────────────────────────────────────────────────────

@app.get("/domains", response_class=HTMLResponse)
async def domains_list(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        servers = s.exec(select(DB.Server).where(DB.Server.is_active == True)).all()
    grouped = []
    for srv in servers:
        result = await AGENT.ssl_all(srv.base_url, srv.agent_token)
        grouped.append({"server": srv, "domains": result.get("domains", []) if result else []})
    return templates.TemplateResponse("domains.html", {"request": request, "grouped": grouped})


@app.post("/domains/check")
async def domains_check(host: str = Form(...), port: int = Form(443),
                        sid: Optional[int] = Form(None), _=Depends(require_login)):
    """Ad-hoc SSL probe via the first active server, or specified."""
    with Session(DB.engine) as s:
        if sid:
            srv = s.exec(select(DB.Server).where(DB.Server.id == sid)).first()
        else:
            srv = s.exec(select(DB.Server).where(DB.Server.is_active == True)).first()
        if not srv:
            return JSONResponse({"error": "no server available"}, status_code=400)
    return await AGENT.ssl_one(srv.base_url, srv.agent_token, host, port)


# ─── Custom Monitors ──────────────────────────────────────────────────────────

@app.get("/monitors", response_class=HTMLResponse)
def monitors_list(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        items = s.exec(select(DB.Monitor).order_by(DB.Monitor.created_at)).all()
        servers = s.exec(select(DB.Server)).all()
    return templates.TemplateResponse("monitors.html", {
        "request": request, "monitors": items, "servers": servers,
    })


@app.get("/monitors/new", response_class=HTMLResponse)
def monitor_new_form(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        servers = s.exec(select(DB.Server)).all()
    return templates.TemplateResponse("monitor_form.html", {
        "request": request, "monitor": None, "servers": servers, "error": None,
    })


@app.post("/monitors/new")
def monitor_create(
    name: str = Form(...), type: str = Form(...), target: str = Form(...),
    expected: str = Form(""), interval_seconds: int = Form(300),
    server_id: Optional[int] = Form(None),
    is_active: str = Form("off"),
    _=Depends(require_login),
):
    with Session(DB.engine) as s:
        m = DB.Monitor(
            server_id=server_id, name=name.strip(), type=type, target=target.strip(),
            expected=expected.strip() or None, interval_seconds=interval_seconds,
            is_active=(is_active == "on"),
        )
        s.add(m); s.commit()
    return RedirectResponse("/monitors", 302)


@app.post("/monitors/{mid}/delete")
def monitor_delete(mid: int, _=Depends(require_login)):
    with Session(DB.engine) as s:
        m = s.exec(select(DB.Monitor).where(DB.Monitor.id == mid)).first()
        if m:
            s.delete(m); s.commit()
    return RedirectResponse("/monitors", 302)


# ─── Alerts ───────────────────────────────────────────────────────────────────

@app.get("/alerts", response_class=HTMLResponse)
def alerts_list(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        items = s.exec(
            select(DB.AlertHistory).order_by(DB.AlertHistory.opened_at.desc()).limit(200)
        ).all()
        servers = {srv.id: srv for srv in s.exec(select(DB.Server)).all()}
    return templates.TemplateResponse("alerts.html", {
        "request": request, "alerts": items, "servers": servers,
    })


@app.post("/alerts/{aid}/ack")
def alert_ack(aid: int, _=Depends(require_login)):
    with Session(DB.engine) as s:
        a = s.exec(select(DB.AlertHistory).where(DB.AlertHistory.id == aid)).first()
        if a:
            a.acked_at = datetime.datetime.utcnow()
            s.add(a); s.commit()
    return RedirectResponse("/alerts", 302)


# ─── Webhook receiver ─────────────────────────────────────────────────────────

@app.post("/webhook/{token}")
async def webhook_receiver(token: str, request: Request):
    """External services post events here.

    Body (JSON):
      {
        "title": "Deploy failed",
        "body": "Build #1234 failed at step 'tests'",
        "level": "warning|critical|info",
        "server": "main-uz",   // optional, matches by name
        "source": "github-actions"
      }

    Token must match WEBHOOK_TOKEN env or per-source registry (future).
    """
    expected = os.getenv("WEBHOOK_TOKEN", "")
    if not expected or not secrets.compare_digest(token, expected):
        return JSONResponse({"error": "invalid token"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    title = str(body.get("title", "Webhook event"))[:200]
    body_text = str(body.get("body", ""))[:2000]
    level = body.get("level", "info").lower()
    source = str(body.get("source", "external"))[:50]
    server_name = body.get("server")

    with Session(DB.engine) as s:
        srv = None
        if server_name:
            srv = s.exec(select(DB.Server).where(DB.Server.name == server_name)).first()

        evt = DB.WebhookEvent(
            source=source, level=level, title=title, body=body_text,
            server_id=srv.id if srv else None,
        )
        s.add(evt); s.commit(); s.refresh(evt)

        # Route: critical/warning → alerts, info → reports
        if level in ("critical", "warning"):
            channel = NOTIFY.resolve_alert_channel(srv)
            icon = "🔴" if level == "critical" else "🟠"
        else:
            channel = NOTIFY.resolve_report_channel(srv)
            icon = "ℹ️"
        text = f"{icon} <b>{NOTIFY.html_escape(title)}</b>\n"
        text += f"<i>{NOTIFY.html_escape(source)}{' · ' + srv.name if srv else ''}</i>\n\n"
        if body_text:
            text += NOTIFY.html_escape(body_text)
        result = await NOTIFY.send_message(channel, text)

        evt.forwarded_to = channel.label if result.get("ok") else "delivery-failed"
        s.add(evt); s.commit()
    return {"ok": True, "id": evt.id, "forwarded_to": evt.forwarded_to}


# ─── AI Chat ──────────────────────────────────────────────────────────────────

@app.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request, _=Depends(require_login)):
    with Session(DB.engine) as s:
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
        msgs = s.exec(
            select(DB.ChatMessage).order_by(DB.ChatMessage.created_at.desc()).limit(50)
        ).all()
        msgs = list(reversed(msgs))
    return templates.TemplateResponse("ai.html", {
        "request": request, "ai": ai, "messages": msgs,
        "configured": ai.enabled and bool(ai.api_key),
    })


@app.post("/ai/chat")
async def ai_chat(prompt: str = Form(...), include_status: str = Form("off"),
                  _=Depends(require_login)):
    with Session(DB.engine) as s:
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
        if not ai or not ai.enabled or not ai.api_key:
            return JSONResponse({"error": "AI sozlanmagan. /settings ga o'ting."}, status_code=400)

        # Save user message
        s.add(DB.ChatMessage(role="user", content=prompt))
        s.commit()

        # Build conversation history (last 20 messages)
        prior = s.exec(
            select(DB.ChatMessage).order_by(DB.ChatMessage.created_at.desc()).limit(20)
        ).all()
        prior = list(reversed(prior))

        # Optional context
        context = None
        if include_status == "on":
            servers = _servers_dict(s)
            context = {"servers": await AGENT.gather_all_status(servers)}

        msgs = [{"role": m.role, "content": m.content} for m in prior]

        reply = AI.chat_once(ai.api_key, ai.model, ai.system_prompt, msgs, context=context)

        s.add(DB.ChatMessage(role="assistant", content=reply))
        s.commit()

    return {"reply": reply}


@app.post("/ai/summarize")
async def ai_summarize(_=Depends(require_login)):
    """One-shot fleet summary."""
    with Session(DB.engine) as s:
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
        if not ai or not ai.enabled or not ai.api_key:
            return JSONResponse({"error": "AI sozlanmagan"}, status_code=400)
        servers = _servers_dict(s)

    statuses = await AGENT.gather_all_status(servers)
    text = AI.summarize_status(ai.api_key, ai.model, ai.system_prompt, statuses)
    return {"reply": text}


@app.post("/ai/clear")
def ai_clear(_=Depends(require_login)):
    with Session(DB.engine) as s:
        for m in s.exec(select(DB.ChatMessage)).all():
            s.delete(m)
        s.commit()
    return RedirectResponse("/ai", 302)


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "", _=Depends(require_login)):
    with Session(DB.engine) as s:
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
    return templates.TemplateResponse("settings.html", {
        "request": request, "ai": ai, "saved": saved,
    })


@app.post("/settings/ai")
def settings_ai_save(
    request: Request,
    api_key: str = Form(""),
    model: str = Form("claude-opus-4-7"),
    system_prompt: str = Form(""),
    enabled: str = Form("off"),
    _=Depends(require_login),
):
    with Session(DB.engine) as s:
        ai = s.exec(select(DB.AISettings).where(DB.AISettings.id == 1)).first()
        # Don't overwrite api_key if blank (preserves existing)
        if api_key.strip():
            ai.api_key = api_key.strip()
        ai.model = model.strip() or "claude-opus-4-7"
        ai.system_prompt = system_prompt.strip() or ai.system_prompt
        ai.enabled = (enabled == "on")
        s.add(ai); s.commit()
    return RedirectResponse("/settings?saved=1", 302)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
