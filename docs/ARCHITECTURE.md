# Arxitektura

## Yuqori darajadagi diagramma

```
                    ┌─────────────────────────────────────┐
                    │          monitor-hub :9991          │
                    │  ┌─────────────────────────────────┐│
                    │  │  Web UI (Jinja2)                ││
                    │  │  • Dashboard  • Servers         ││
                    │  │  • Monitors   • Alerts          ││
                    │  │  • Backups    • SSL/Domains     ││
                    │  │  • AI Chat    • Settings        ││
                    │  └─────────────────────────────────┘│
                    │  ┌─────────────────────────────────┐│
                    │  │  Background Scheduler (asyncio) ││
                    │  │  • Watchdog tick (60s)          ││
                    │  │  • Resource tick (300s)         ││
                    │  │  • SSL daily (06:00)            ││
                    │  │  • Backup daily (02:00)         ││
                    │  │  • Daily digest (08:00)         ││
                    │  └─────────────────────────────────┘│
                    │  ┌─────────────────────────────────┐│
                    │  │  Notifier (Telegram routing)    ││
                    │  └─────────────────────────────────┘│
                    │  ┌─────────────────────────────────┐│
                    │  │  SQLite                         ││
                    │  │  servers, alerts, check_runs,   ││
                    │  │  webhooks, ai_chat              ││
                    │  └─────────────────────────────────┘│
                    └──────────────┬──────────────────────┘
                                   │ HTTP + Bearer
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│ Server #1    │           │ Server #2    │           │ Server #N    │
│              │           │              │           │              │
│ monitor-     │           │ monitor-     │           │ monitor-     │
│  agent :9990 │           │  agent :9990 │           │  agent :9990 │
│  ┌─────────┐ │           │  ┌─────────┐ │           │  ┌─────────┐ │
│  │/status  │ │           │  │/status  │ │           │  │/status  │ │
│  │/backup  │ │           │  │/backup  │ │           │  │/backup  │ │
│  │/ssl     │ │           │  │/ssl     │ │           │  │/ssl     │ │
│  └─────────┘ │           │  └─────────┘ │           │  └─────────┘ │
│  config.yml  │           │  config.yml  │           │  config.yml  │
│  docker.sock │           │  docker.sock │           │  docker.sock │
└──────────────┘           └──────────────┘           └──────────────┘
        │                          │                          │
        │  (har serverda kuzatadi: containerlar, endpointlar, │
        │   bazalar, disk/RAM/CPU, SSL, backuplar)             │
        ▼                          ▼                          ▼
   ───────────────  Docker Engine + monitorned services  ──────


                    ┌─────────────────────────────────────┐
                    │  Telegram Bot API                   │
                    │  • Default: @mkdevbackupbot         │
                    │  • Per-server overrides             │
                    │  • Alert vs Report routing          │
                    └─────────────────────────────────────┘
```

## Ma'lumot oqimi

### Watchdog tick (har 60 soniyada)

```
Hub Scheduler
    │
    ▼
Pull /status from each active server (asyncio.gather)
    │
    ▼
For each server:
    ├─ Compare to previous AlertHistory rows (open ones)
    ├─ For each new failure:
    │     │
    │     ├─ Insert/increment AlertHistory(consecutive_count++)
    │     ├─ If consecutive_count >= CONFIRM_TICKS:
    │     │     ├─ If maintenance_until → suppress (mark fired)
    │     │     └─ Else → send Telegram → mark fired
    │     └─ Continue
    ├─ For each recovery:
    │     ├─ Mark AlertHistory.resolved_at
    │     └─ If was previously fired → send recovery message
    └─ Update Server.last_check_at, last_status
        Insert CheckRun for timeline
```

### Telegram routing

```
Send alert for Server X
    │
    ▼
resolve_alert_channel(server)
    │
    ├─ server.alert_bot_token + server.alert_chat_id set?
    │       └─ Yes → use these
    │
    └─ No → use TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID env
            (fallback: TELEGRAM_CHAT_ID)
    ▼
HTTP POST → api.telegram.org/bot{TOKEN}/sendMessage
    │
    ▼
Persist delivered_chat_id + delivered_via_bot to AlertHistory
```

### Alert state machine

```
                    ┌──────────────┐
   tick: bad        │              │  tick: bad (count++)
   ───────────────► │  WATCHING    │ ───────────────────┐
                    │ (count = 1)  │                    │
                    │              │ ◄──────────────────┘
                    └──────┬───────┘     count < CONFIRM_TICKS
                           │
                           │ count >= CONFIRM_TICKS
                           ▼
                    ┌──────────────┐
                    │   ACTIVE     │ ─── admin acks ───► ACKED
                    │  (Telegram   │
                    │   sent)      │
                    └──────┬───────┘
                           │
                           │ tick: ok
                           ▼
                    ┌──────────────┐
                    │  RESOLVED    │ ─── recovery alert sent ───►
                    │              │
                    └──────────────┘
```

## Komponentlar

### monitor-agent

**Vazifa:** bitta serverda turadi va shu server haqida ma'lumot beradi. Centralga bog'liq emas (mustaqil).

**Fayllar:**
```
monitor-agent/
├── app/main.py          # FastAPI + endpointlar
├── Dockerfile
├── docker-compose.yml
├── config.yml           # endpoints, databases, backups, domains, thresholds
├── .agent-secret        # Bearer token (har serverda yagona)
└── backups/             # local backup storage
```

**Mounts:**
- `/var/run/docker.sock` (RW) — `docker ps`, `docker exec` uchun
- `/` → `/host` (RO) — `/proc/meminfo`, `/proc/loadavg`, sqlite copy uchun

**Endpointlar:**

| Path | Method | Maqsad |
|------|--------|--------|
| `/health` | GET | Yashash ko'rsatkichi (auth yo'q) |
| `/status` | GET | To'liq holat (containers + resources + endpoints + databases) |
| `/containers` | GET | Faqat containerlar |
| `/resources` | GET | Faqat disk/RAM/load |
| `/endpoints` | GET | Configdagi HTTP endpointlarni probe qilish |
| `/databases` | GET | Configdagi DB tekshiruvi |
| `/ssl?host=X&port=443` | GET | Bitta domen sertifikati |
| `/ssl/all` | GET | Configdagi domenlar |
| `/backup/run` | POST | Hamma backuplarni ishga tushirish |
| `/backup/list` | GET | Saqlangan fayllar |
| `/backup/file/{name}` | GET | Bitta faylni stream qilish |
| `/config` | GET | Joriy config qaytarish |
| `/reload` | POST | config.yml ni qayta o'qish |

### monitor-hub

**Vazifa:** markaz. Web UI + scheduler + Telegram + AI.

**Fayllar:**
```
monitor-hub/
├── app/
│   ├── main.py          # FastAPI route'lar
│   ├── db.py            # SQLModel modellar + migration
│   ├── agent_client.py  # Agent'larga HTTP wrapper
│   ├── notify.py        # Telegram routing
│   ├── scheduler.py     # Background asyncio tasks
│   ├── ai.py            # Claude integratsiyasi
│   ├── templates/       # Jinja2 sahifalar
│   └── static/
├── data/                # SQLite + (kelajakda) cache
├── Dockerfile
├── docker-compose.yml
├── .env                 # ADMIN_PASS, TELEGRAM_*, etc.
└── .session-key         # cookie session secret
```

### n8n-workflows

**Vazifa:** Hub'dan tashqari avtomatik vazifalar (GitHub digest va boshqalar).

**Workflows:**
- `01-server-watchdog.json` — eski watchdog (Hub bor bo'lgani uchun ixtiyoriy)
- `02-resource-alert.json` — eski (ixtiyoriy)
- `03-ssl-watcher.json` — eski (ixtiyoriy)
- `04-daily-backup.json` — eski (ixtiyoriy)
- `05-daily-digest.json` — eski (ixtiyoriy)
- `06-github-tracker-daily.json` — **GitHub kunlik digest**
- `07-github-tracker-weekly.json` — **GitHub haftalik digest**

> **Eslatma:** Hub o'zining scheduler'iga ega bo'lgani uchun, monitoring ishlari (1-5)
> ikki marta yubormaslik uchun birini o'chirib qo'yish tavsiya etiladi.
> Hub asosiy bo'lsa — n8n 01-05 ni deactivate qiling. GitHub workflowlari (06-07) qoladi.

## DB sxemalari

### `server`
| Column | Type | Maqsad |
|--------|------|--------|
| id | INT PK | |
| name | UNIQUE | masalan `main-uz`, `dev-server` |
| base_url | TEXT | `http://IP:9990` |
| agent_token | TEXT | Bearer auth |
| description | TEXT? | |
| is_active | BOOL | inactive bo'lsa nazorat qilinmaydi |
| alert_bot_token | TEXT? | per-server override |
| alert_chat_id | TEXT? | per-server override |
| report_bot_token | TEXT? | per-server override |
| report_chat_id | TEXT? | per-server override |
| maintenance_until | DATETIME? | bu vaqtgacha alert tindiriladi |
| last_check_at | DATETIME? | scheduler eng so'nggi kuzatuvi |
| last_status | TEXT? | ok / degraded / down |

### `alerthistory`
| Column | Type | Maqsad |
|--------|------|--------|
| id | INT PK | |
| server_id | INT FK | |
| monitor_type | TEXT | container / endpoint / database / resource / ssl / agent / custom |
| key | TEXT | dedup key, masalan `container::n8n` |
| level | TEXT | warning / critical |
| message | TEXT | HTML xabar |
| consecutive_count | INT | qancha tick ketma-ket |
| fired | BOOL | Telegram'ga yuborildimi |
| opened_at | DATETIME | birinchi qachon ko'rdik |
| fired_at | DATETIME? | qachon Telegram'ga yuborildi |
| resolved_at | DATETIME? | qachon tiklandi |
| acked_at | DATETIME? | qachon ack qilindi |
| delivered_chat_id | TEXT? | qaysi kanalga ketdi |
| delivered_via_bot | TEXT? | qaysi bot orqali |

### `checkrun`
Har watchdog tick uchun bitta yozuv (timeline va debugging uchun).

### `webhookevent`
Tashqi webhook receiver natijalari.

### `aisettings`
Singleton — Anthropic API key, model, system prompt.

### `chatmessage`
AI suhbat tarixi.

## Background scheduler

- **asyncio task**'lar Python jarayonida ishlaydi (alohida kontainer kerak emas)
- Har bir task `while running: try: await tick(); except: log; await asyncio.sleep(interval)`
- Daily cron tasks: `await asyncio.sleep(seconds_until_target)` keyin tick
- Yengil va deterministik

## Konfiguratsiya

### Hub (env)
- `ADMIN_USER`, `ADMIN_PASS` — Web UI login
- `SECRET_KEY` — cookie session
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — default kanal
- `TELEGRAM_ALERT_CHAT_ID`, `TELEGRAM_REPORT_CHAT_ID` — ixtiyoriy split
- `WATCHDOG_INTERVAL`, `RESOURCE_INTERVAL`, `CONFIRM_TICKS`
- `WEBHOOK_TOKEN` — webhook receiver token
- `HUB_SCHEDULER_ENABLED=true|false`

### Agent (config.yml)
- `server_name`
- `endpoints[]` — HTTP healthcheck'lar
- `databases[]` — Postgres + SQLite
- `backups[]` — pg_dump / sqlite_copy / directory
- `domains[]` — SSL nazorat
- `thresholds.disk_pct, mem_pct, load_1m`
- `backup_retention_days`
