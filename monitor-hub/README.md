# monitor-hub

Markaziy boshqaruv paneli. Web UI + scheduler + Telegram routing + AI yordamchi.

## Tezkor o'rnatish

```bash
git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
cd /opt/monitoring/monitor-hub

cp .env.example .env
# .env ni tahrirlang — ADMIN_PASS, TELEGRAM_*, etc.

docker compose up -d --build

# Login: http://YOUR_HOST:9991
# admin + .env ichidagi parol
```

## Xususiyatlar

- ✅ **Web UI (iOS-style)** — Dashboard, server CRUD, monitorlar, alertlar, backuplar, SSL, AI chat
- ✅ **Background scheduler** — har 60s status, har 5m resurs, kunlik SSL/backup/digest
- ✅ **Smart alerting** — anti-flapping (CONFIRM_TICKS), recovery xabar, debounce
- ✅ **Per-server Telegram routing** — har server o'z bot/chat'ini belgilaydi
- ✅ **Maintenance mode** — rejalashtirilgan ish davomida alertlar tindiriladi
- ✅ **Webhook receiver** — tashqi servislar event yuborishi mumkin
- ✅ **AI yordamchi** — Anthropic Claude bilan chat (server holatini kontekstda)
- ✅ **SQLite** — tashqi DB kerak emas

## Sozlamalar

- `.env` faylida — qarang [`.env.example`](.env.example)
- Web UI **Sozlamalar** sahifasi — AI API kalit, model
- Server-level — UI'dagi Server tahrirlash sahifasi (alert/report kanallari, maintenance)

To'liq batafsil: [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md)

## API

Hub o'z API ni ham taqdim etadi:
- `GET /api/dashboard` — JSON status barcha serverlar
- `POST /webhook/<token>` — tashqi event qabul qilish

To'liq: [`docs/API.md`](../docs/API.md)

## DB

SQLite, `/app/data/hub.db`. Volume mount orqali persistent.

Schema migration avtomat (`db.py` ichida `init_db()`).

## Loglar

```bash
docker logs monitor-hub --tail 100 -f
```

Watchdog tick'lar har 60 soniyada ko'rinadi:
```
hub.sched | [watchdog] tick took 0.4s
httpx | HTTP Request: GET http://172.17.0.1:9990/status "200 OK"
```

## Troubleshooting

### Telegram yubormayapti
```bash
# Bot tekshirish
curl https://api.telegram.org/bot<TOKEN>/getMe

# Hub log
docker logs monitor-hub | grep -i telegram
```

### Migration xato
```bash
docker compose down
rm -rf data/hub.db*
docker compose up -d --build
```

### Scheduler ishlamayapti
`.env` da `HUB_SCHEDULER_ENABLED=true` ekanini tekshiring.
