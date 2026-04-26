"""
Hub-internal continuous monitoring scheduler.

Runs as background asyncio tasks:
  - Watchdog tick (every WATCHDOG_INTERVAL seconds, default 60)
       Pulls /status from each active server, diffs vs previous state,
       creates AlertHistory rows, fires Telegram on first confirmed failure.
  - Resource tick (every RESOURCE_INTERVAL seconds, default 300)
       Pulls /resources, threshold checks with 30-min debounce.
  - SSL tick (daily 06:00 server-local)
       Pulls /ssl/all, alerts on <14d.
  - Backup tick (daily 02:00)
       Triggers /backup/run on each, sends summary report.
  - Daily digest (daily 08:00)
       Sends rich daily report to report channel(s).

Alert state machine:
  • OK→BAD on first detection: row inserted with consecutive_count=1, fired=false
  • BAD→BAD next tick: consecutive_count++; once >= CONFIRM_TICKS, fire & set fired=true, send Telegram
  • BAD→OK: mark resolved, send recovery if previously fired
  • Maintenance window suppresses fired delivery (state still tracked).
"""
from __future__ import annotations

import os
import json
import asyncio
import logging
import datetime
from typing import Optional

from sqlmodel import Session, select

from . import db as DB
from . import agent_client as AGENT
from . import notify as NOTIFY

log = logging.getLogger("hub.sched")

WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))      # seconds
RESOURCE_INTERVAL = int(os.getenv("RESOURCE_INTERVAL", "300"))    # seconds
CONFIRM_TICKS = int(os.getenv("CONFIRM_TICKS", "2"))              # ticks before firing alert
DEBOUNCE_RESOURCE_SEC = int(os.getenv("DEBOUNCE_RESOURCE_SEC", "1800"))  # 30 min


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_in_maintenance(srv: DB.Server) -> bool:
    return bool(srv.maintenance_until and srv.maintenance_until > datetime.datetime.utcnow())


def _existing_open(s: Session, server_id: int, monitor_type: str, key: str) -> Optional[DB.AlertHistory]:
    return s.exec(
        select(DB.AlertHistory)
        .where(DB.AlertHistory.server_id == server_id)
        .where(DB.AlertHistory.monitor_type == monitor_type)
        .where(DB.AlertHistory.key == key)
        .where(DB.AlertHistory.resolved_at == None)  # noqa: E711
        .order_by(DB.AlertHistory.opened_at.desc())
    ).first()


async def _maybe_fire(s: Session, srv: DB.Server, alert: DB.AlertHistory, format_html: str):
    """Decide whether to actually send the Telegram message."""
    if alert.fired:
        return  # already fired
    if alert.consecutive_count < CONFIRM_TICKS:
        return  # not yet confirmed
    if _is_in_maintenance(srv):
        log.info(f"[{srv.name}] maintenance — suppressing alert {alert.key}")
        alert.fired = True
        alert.fired_at = datetime.datetime.utcnow()
        alert.delivered_via_bot = "suppressed"
        alert.delivered_chat_id = "maintenance"
        s.add(alert); s.commit()
        return

    channel = NOTIFY.resolve_alert_channel(srv)
    result = await NOTIFY.send_message(channel, format_html)
    alert.fired = True
    alert.fired_at = datetime.datetime.utcnow()
    if result.get("ok"):
        alert.delivered_chat_id = channel.chat_id
        alert.delivered_via_bot = channel.bot_id
    else:
        alert.delivered_chat_id = "delivery-failed"
        alert.delivered_via_bot = str(result.get("error"))[:100]
    s.add(alert); s.commit()


async def _maybe_recover(s: Session, srv: DB.Server, alert: DB.AlertHistory, format_html: str):
    """Send recovery message if the alert had previously been fired."""
    alert.resolved_at = datetime.datetime.utcnow()
    s.add(alert)
    if alert.fired and not _is_in_maintenance(srv):
        channel = NOTIFY.resolve_alert_channel(srv)
        await NOTIFY.send_message(channel, format_html)
    s.commit()


# ─── Watchdog tick ────────────────────────────────────────────────────────────

async def watchdog_tick():
    """One pass over all active servers."""
    with Session(DB.engine) as s:
        servers = list(s.exec(select(DB.Server).where(DB.Server.is_active == True)).all())

    if not servers:
        return

    async def one(srv: DB.Server):
        t0 = datetime.datetime.utcnow()
        st = await AGENT.status(srv.base_url, srv.agent_token)
        elapsed_ms = int((datetime.datetime.utcnow() - t0).total_seconds() * 1000)
        return srv, st, elapsed_ms

    results = await asyncio.gather(*[one(s) for s in servers], return_exceptions=True)

    with Session(DB.engine) as s:
        for r in results:
            if isinstance(r, Exception):
                log.error(f"watchdog gather error: {r}")
                continue
            srv, st, elapsed_ms = r
            await _process_status(s, srv, st, elapsed_ms)


async def _process_status(s: Session, srv: DB.Server, st: dict, elapsed_ms: int):
    """Compare current status to last AlertHistory rows and update."""
    # 1) Server-level reachability
    reachable = bool(st) and "_error" not in st

    if not reachable:
        await _track_failure(
            s, srv, "agent", "agent::reachability",
            f"🔴 <b>{srv.name}</b> — monitor-agent javob bermayapti\n"
            f"Xato: <code>{NOTIFY.html_escape(str(st.get('_error', 'unknown'))[:200])}</code>",
            level="critical",
        )
        # Update server snapshot
        srv.last_check_at = datetime.datetime.utcnow()
        srv.last_status = "down"
        s.add(srv)
        s.add(DB.CheckRun(server_id=srv.id, duration_ms=elapsed_ms, status="down",
                          summary=str(st.get('_error', '?'))[:500]))
        s.commit()
        return

    await _track_recovery(s, srv, "agent", "agent::reachability",
                          f"🟢 <b>{srv.name}</b> — monitor-agent tiklandi")

    # 2) Containers
    bad_states = {"exited", "restarting", "dead", "removing"}
    for c in (st.get("containers") or []):
        key = f"container::{c['name']}"
        bad = c["health"] == "unhealthy" or c["state"] in bad_states
        if bad:
            level = "critical" if c["state"] in bad_states else "warning"
            msg = (f"⚠️ <b>{srv.name}</b> — container <code>{c['name']}</code> "
                   f"holati: {c['health']}/{c['state']}\n"
                   f"<i>{NOTIFY.html_escape(c.get('status', ''))[:200]}</i>")
            await _track_failure(s, srv, "container", key, msg, level=level)
        else:
            await _track_recovery(s, srv, "container", key,
                                  f"✅ <b>{srv.name}</b> — container <code>{c['name']}</code> tiklandi")

    # 3) Endpoints
    for e in (st.get("endpoints") or []):
        key = f"endpoint::{e['name']}"
        if not e["ok"]:
            err = e.get("error") or f"HTTP {e.get('status')}"
            msg = (f"🔌 <b>{srv.name}</b> — endpoint <code>{e['name']}</code> javob bermayapti\n"
                   f"URL: <code>{e['url']}</code>\n"
                   f"Xato: <code>{NOTIFY.html_escape(str(err))[:200]}</code>")
            await _track_failure(s, srv, "endpoint", key, msg, level="critical")
        else:
            await _track_recovery(s, srv, "endpoint", key,
                                  f"✅ <b>{srv.name}</b> — endpoint <code>{e['name']}</code> tiklandi")

    # 4) Databases
    for db in (st.get("databases") or []):
        key = f"db::{db['name']}"
        if not db["ok"]:
            msg = (f"💾 <b>{srv.name}</b> — DB <code>{db['name']}</code> ({db['type']}) "
                   f"javob bermayapti\n"
                   f"Xato: <code>{NOTIFY.html_escape(str(db.get('error', '?')))[:200]}</code>")
            await _track_failure(s, srv, "database", key, msg, level="critical")
        else:
            await _track_recovery(s, srv, "database", key,
                                  f"✅ <b>{srv.name}</b> — DB <code>{db['name']}</code> tiklandi")

    # 5) Update server snapshot
    bad_count = (
        sum(1 for c in (st.get("containers") or [])
            if c["health"] == "unhealthy" or c["state"] in bad_states) +
        sum(1 for e in (st.get("endpoints") or []) if not e["ok"]) +
        sum(1 for d in (st.get("databases") or []) if not d["ok"])
    )
    status_label = "ok" if bad_count == 0 else ("degraded" if bad_count < 3 else "down")
    srv.last_check_at = datetime.datetime.utcnow()
    srv.last_status = status_label
    s.add(srv)

    # Light check_run record
    s.add(DB.CheckRun(server_id=srv.id, duration_ms=elapsed_ms, status=status_label,
                      summary=f"containers={len(st.get('containers') or [])} "
                              f"endpoints={len(st.get('endpoints') or [])} "
                              f"dbs={len(st.get('databases') or [])} bad={bad_count}"))
    s.commit()


async def _track_failure(s: Session, srv: DB.Server, monitor_type: str, key: str,
                         message_html: str, level: str = "warning"):
    """Increment consecutive_count, maybe fire."""
    open_alert = _existing_open(s, srv.id, monitor_type, key)
    if open_alert:
        open_alert.consecutive_count += 1
        open_alert.message = message_html  # update with latest detail
        open_alert.level = level
        s.add(open_alert)
        await _maybe_fire(s, srv, open_alert, message_html)
    else:
        new_alert = DB.AlertHistory(
            server_id=srv.id, monitor_type=monitor_type, key=key,
            level=level, message=message_html, consecutive_count=1, fired=False,
        )
        s.add(new_alert); s.commit(); s.refresh(new_alert)
        await _maybe_fire(s, srv, new_alert, message_html)


async def _track_recovery(s: Session, srv: DB.Server, monitor_type: str, key: str,
                          recovery_html: str):
    open_alert = _existing_open(s, srv.id, monitor_type, key)
    if open_alert:
        await _maybe_recover(s, srv, open_alert, recovery_html)


# ─── Resource tick (thresholds) ───────────────────────────────────────────────

async def resource_tick():
    with Session(DB.engine) as s:
        servers = list(s.exec(select(DB.Server).where(DB.Server.is_active == True)).all())

    async def one(srv: DB.Server):
        return srv, await AGENT.resources(srv.base_url, srv.agent_token)

    results = await asyncio.gather(*[one(s) for s in servers], return_exceptions=True)

    with Session(DB.engine) as s:
        for r in results:
            if isinstance(r, Exception):
                continue
            srv, data = r
            if not data or "_error" in data:
                continue
            t = data.get("thresholds") or {"disk_pct": 80, "mem_pct": 85, "load_1m": 5}

            for fs in (data.get("disk") or []):
                key = f"disk::{fs['mount']}"
                if fs["used_pct"] >= t["disk_pct"]:
                    free_g = fs["available_bytes"] / (1024**3)
                    msg = (f"💾 <b>{srv.name}</b> — disk <code>{fs['mount']}</code> "
                           f"{fs['used_pct']}% to'la ({free_g:.1f}G qoldi)")
                    await _track_failure(s, srv, "resource", key, msg, level="warning")
                else:
                    await _track_recovery(s, srv, "resource", key,
                                          f"✅ <b>{srv.name}</b> — disk <code>{fs['mount']}</code> "
                                          f"yana {100 - fs['used_pct']}% bo'sh")

            m = data.get("memory") or {}
            if m and m.get("used_pct", 0) >= t["mem_pct"]:
                msg = (f"🧠 <b>{srv.name}</b> — RAM {m['used_pct']}% band "
                       f"({m['used_bytes']/(1024**3):.1f}G/{m['total_bytes']/(1024**3):.1f}G)")
                await _track_failure(s, srv, "resource", "mem", msg, level="warning")
            else:
                await _track_recovery(s, srv, "resource", "mem",
                                      f"✅ <b>{srv.name}</b> — RAM normallashdi")

            l = data.get("load") or {}
            if l.get("1m", 0) >= t["load_1m"]:
                msg = (f"⚡ <b>{srv.name}</b> — load yuqori: "
                       f"1m={l['1m']} 5m={l['5m']} 15m={l['15m']}")
                await _track_failure(s, srv, "resource", "load", msg, level="warning")
            else:
                await _track_recovery(s, srv, "resource", "load",
                                      f"✅ <b>{srv.name}</b> — load normallashdi")


# ─── SSL tick (daily) ─────────────────────────────────────────────────────────

async def ssl_tick():
    with Session(DB.engine) as s:
        servers = list(s.exec(select(DB.Server).where(DB.Server.is_active == True)).all())

    for srv in servers:
        result = await AGENT.ssl_all(srv.base_url, srv.agent_token)
        if not result or "_error" in result:
            continue
        critical, warning = [], []
        for d in result.get("domains") or []:
            if not d["ok"]:
                critical.append(f"✗ {d['host']}:{d['port']} — {(d.get('error') or 'check failed')[:60]}")
                continue
            days = d["days_left"]
            if days <= 3:
                critical.append(f"🔴 {d['host']} — {days} kun qoldi ({d['expires_at'][:10]})")
            elif days <= 14:
                warning.append(f"🟠 {d['host']} — {days} kun qoldi ({d['expires_at'][:10]})")
        if not critical and not warning:
            continue
        text = f"🔒 <b>SSL</b> — <b>{srv.name}</b>\n\n"
        if critical:
            text += "<b>Kritik</b>:\n" + "\n".join(critical) + "\n\n"
        if warning:
            text += "<b>Diqqat</b>:\n" + "\n".join(warning)
        # SSL warnings go to alert channel
        ch = NOTIFY.resolve_alert_channel(srv)
        await NOTIFY.send_message(ch, text)


# ─── Backup tick (daily 02:00) ────────────────────────────────────────────────

async def backup_tick():
    with Session(DB.engine) as s:
        servers = list(s.exec(select(DB.Server).where(DB.Server.is_active == True)).all())

    for srv in servers:
        result = await AGENT.backup_run(srv.base_url, srv.agent_token)
        if not result:
            await NOTIFY.send_message(
                NOTIFY.resolve_alert_channel(srv),
                f"🔴 <b>{srv.name}</b> — backup ishga tushirib bo'lmadi (agent javob bermadi)"
            )
            continue
        if "_error" in result:
            await NOTIFY.send_message(
                NOTIFY.resolve_alert_channel(srv),
                f"🔴 <b>{srv.name}</b> — backup xato: <code>{result['_error'][:200]}</code>"
            )
            continue

        results_list = result.get("results") or []
        ok_count = sum(1 for r in results_list if r["ok"])
        bad_count = sum(1 for r in results_list if not r["ok"])

        # Summary to report channel
        text = f"📦 <b>Backup</b> — <b>{srv.name}</b>\n\n"
        for r in results_list:
            if r["ok"]:
                sz = r.get("size_bytes", 0)
                sz_s = f"{sz/(1024**2):.1f}M" if sz > 1024*1024 else f"{sz//1024}K"
                text += f"  ✅ {r['name']} — {sz_s}\n"
            else:
                text += f"  ❌ {r['name']} — {(r.get('error') or 'failed')[:80]}\n"
        text += f"\n{'✓ Xatosiz' if bad_count == 0 else f'⚠️ {bad_count} ta xato'}"

        ch_report = NOTIFY.resolve_report_channel(srv)
        await NOTIFY.send_message(ch_report, text)

        # If any failed → alert channel too
        if bad_count > 0:
            ch_alert = NOTIFY.resolve_alert_channel(srv)
            if ch_alert.bot_token != ch_report.bot_token or ch_alert.chat_id != ch_report.chat_id:
                await NOTIFY.send_message(ch_alert,
                    f"🔴 <b>{srv.name}</b> — backup'da {bad_count} ta xato. Tafsilot reports kanalida.")


# ─── Daily digest (08:00) ─────────────────────────────────────────────────────

async def daily_digest():
    """Send a daily report per server to its report channel."""
    with Session(DB.engine) as s:
        servers = list(s.exec(select(DB.Server).where(DB.Server.is_active == True)).all())

    for srv in servers:
        st = await AGENT.status(srv.base_url, srv.agent_token)
        if not st or "_error" in st:
            text = f"☀️ <b>{srv.name}</b> — kunlik hisobot\n\n🔴 Server javob bermayapti."
        else:
            containers = st.get("containers") or []
            eps = st.get("endpoints") or []
            dbs = st.get("databases") or []
            healthy_c = sum(1 for c in containers
                            if c["state"] == "running" and c["health"] in ("healthy", "none"))
            ok_eps = sum(1 for e in eps if e["ok"])
            ok_dbs = sum(1 for d in dbs if d["ok"])
            disk = next((d for d in (st.get("disk") or []) if d["mount"] in ("/host", "/")),
                        (st.get("disk") or [{}])[0])
            mem = st.get("memory") or {}
            load = st.get("load") or {}
            uptime_d = (st.get("uptime_seconds") or 0) // 86400
            text = (
                f"☀️ <b>{srv.name}</b> — kunlik hisobot\n\n"
                f"⏱ Uptime: {uptime_d} kun\n"
                f"📦 Containers: {healthy_c}/{len(containers)}\n"
                f"🔌 Endpoints: {ok_eps}/{len(eps)}\n"
                f"💾 Bazalar: {ok_dbs}/{len(dbs)}\n"
                f"📊 Disk {disk.get('used_pct', 0)}% · "
                f"RAM {mem.get('used_pct', 0)}% · "
                f"Load {load.get('1m', 0)}\n"
            )
            bad_c = [c for c in containers if c["state"] != "running" or c["health"] == "unhealthy"]
            bad_e = [e for e in eps if not e["ok"]]
            bad_d = [d for d in dbs if not d["ok"]]
            if bad_c or bad_e or bad_d:
                text += "\n<b>⚠️ Diqqat:</b>\n"
                for c in bad_c: text += f"  • container {c['name']} — {c['health']}/{c['state']}\n"
                for e in bad_e: text += f"  • endpoint {e['name']} — {e.get('status', 'ERR')}\n"
                for d in bad_d: text += f"  • db {d['name']} — {(d.get('error') or '?')[:60]}\n"

        await NOTIFY.send_message(NOTIFY.resolve_report_channel(srv), text)


# ─── Main loop ────────────────────────────────────────────────────────────────

class Scheduler:
    """Owns the asyncio loops."""

    def __init__(self):
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def _loop(self, name: str, interval: int, fn):
        while self._running:
            try:
                t0 = asyncio.get_running_loop().time()
                await fn()
                dt = asyncio.get_running_loop().time() - t0
                log.debug(f"[{name}] tick took {dt:.1f}s")
            except Exception as e:
                log.exception(f"[{name}] tick error: {e}")
            await asyncio.sleep(interval)

    async def _cron(self, name: str, hour: int, minute: int, fn):
        """Daily at specific time (server-local)."""
        while self._running:
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            wait_s = (target - now).total_seconds()
            log.info(f"[{name}] next run in {wait_s/3600:.1f}h ({target})")
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                break
            try:
                await fn()
            except Exception as e:
                log.exception(f"[{name}] cron error: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._loop("watchdog", WATCHDOG_INTERVAL, watchdog_tick)),
            loop.create_task(self._loop("resource", RESOURCE_INTERVAL, resource_tick)),
            loop.create_task(self._cron("ssl-daily", 6, 0, ssl_tick)),
            loop.create_task(self._cron("backup-daily", 2, 0, backup_tick)),
            loop.create_task(self._cron("daily-digest", 8, 0, daily_digest)),
        ]
        log.info(f"Scheduler started: watchdog={WATCHDOG_INTERVAL}s resource={RESOURCE_INTERVAL}s")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


scheduler = Scheduler()
