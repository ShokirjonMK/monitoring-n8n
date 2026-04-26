# HTTP API ma'lumotnomasi

## monitor-agent (port 9990)

Auth: `Authorization: Bearer <agent_token>` (har bir endpoint, `/health` dan tashqari)

### `GET /health`
**Auth:** yo'q
```json
{"status":"ok","agent":"monitor-agent","server":"main-uz"}
```

### `GET /status`
Eng ko'p ma'lumot — barchasini bir martada qaytaradi.
```json
{
  "server": "main-uz",
  "timestamp": "2026-04-26T08:00:00",
  "uptime_seconds": 3926572,
  "containers": [
    {"name":"n8n","image":"n8nio/n8n:latest","status":"Up 1h",
     "state":"running","health":"none","ports":"...","created":"...","running_for":"..."}
  ],
  "disk": [{"filesystem":"/dev/sda1","mount":"/host","total_bytes":...,"used_bytes":...,"available_bytes":...,"used_pct":40}],
  "memory": {"total_bytes":...,"available_bytes":...,"used_bytes":...,"used_pct":62.3,
             "swap_total_bytes":0,"swap_used_bytes":0},
  "load": {"1m":2.7, "5m":2.5, "15m":2.4},
  "endpoints": [{"name":"DataGate","url":"...","status":200,"expected":200,"ok":true,"elapsed_ms":82}],
  "databases": [{"name":"app_db","type":"postgres","ok":true,
                 "info":{"size_bytes":12345678,"active_connections":7}}],
  "thresholds": {"disk_pct":80,"mem_pct":85,"load_1m":5.0}
}
```

### `GET /containers`
Faqat container ma'lumotlari.

### `GET /resources`
Disk + memory + load + uptime.

### `GET /endpoints`
Configdagi HTTP endpointlarning probe natijasi.

### `GET /databases`
DB connection status va size.

### `GET /ssl?host={host}&port={port}`
Bitta domen SSL.
```json
{"host":"example.com","port":443,"ok":true,"expires_at":"2026-12-31T23:59:59+00:00",
 "days_left":250,"issuer":"...","subject":"..."}
```

### `GET /ssl/all`
Configdagi barcha domenlar.

### `POST /backup/run`
Konfigda ko'rsatilgan barcha backuplarni ishga tushiradi.
```json
{
  "server":"main-uz",
  "results":[
    {"name":"app_db","type":"pg_dump","ok":true,
     "filename":"app_db-20260426-020000.sql.gz","size_bytes":12345678}
  ],
  "cleaned_old_backups":3,
  "ok":true
}
```

### `GET /backup/list`
Saqlangan backup fayllar.

### `GET /backup/file/{filename}`
Faylni binary stream sifatida qaytaradi (`Content-Disposition: attachment`).

### `GET /config`
Joriy `config.yml`.

### `POST /reload`
`config.yml` ni qayta o'qiydi.

---

## monitor-hub (port 9991)

Auth: session cookie (login orqali) yoki webhook uchun token URL'da.

### Web UI sahifalar (HTML)
- `GET /` — Dashboard
- `GET /login`, `POST /login`, `GET /logout`
- `GET /servers`, `GET /servers/new`, `POST /servers/new`
- `GET /servers/{sid}`, `GET /servers/{sid}/edit`, `POST /servers/{sid}/edit`
- `POST /servers/{sid}/delete`
- `POST /servers/{sid}/probe` (manual health check)
- `POST /servers/{sid}/test-channels` (Telegram kanallarni sinash)
- `GET /backups`, `POST /backups/run/{sid}`
- `GET /domains`, `POST /domains/check`
- `GET /monitors`, `GET /monitors/new`, `POST /monitors/new`, `POST /monitors/{mid}/delete`
- `GET /alerts`, `POST /alerts/{aid}/ack`
- `GET /ai`, `POST /ai/chat`, `POST /ai/summarize`, `POST /ai/clear`
- `GET /settings`, `POST /settings/ai`

### JSON API
- `GET /api/dashboard` — barcha serverlar live status (auth kerak)
- `GET /healthz` — Hub yashash ko'rsatkichi (auth yo'q)

### Webhook receiver

```
POST /webhook/{WEBHOOK_TOKEN}
```

Body (JSON):
```json
{
  "title": "Deploy failed",                      // majburiy, max 200 char
  "body": "Build #1234 failed at 'tests' step",  // ixtiyoriy, max 2000 char
  "level": "warning",                            // info | warning | critical
  "server": "main-uz",                           // ixtiyoriy — per-server routing
  "source": "github-actions"                     // ixtiyoriy label
}
```

Javob:
```json
{"ok": true, "id": 42, "forwarded_to": "default-alert"}
```

Routing:
- `level=critical` yoki `warning` → alert kanaliga
- `level=info` → report kanaliga
- `server` mavjud bo'lsa — server'ning per-server kanali

### Misollar

#### Kursdagi kompaniyaga server qo'shish (curl orqali)

Hub UI faqat — bu API JSON emas, form-based.

#### Manual backup boshlash
```bash
HUB_HOST=http://localhost:9991
HUB_USER=admin
HUB_PASS=$(cat /opt/monitor-hub/.admin-pass)

# 1. Login va cookie saqlash
curl -s -c /tmp/c -d "username=$HUB_USER&password=$HUB_PASS" -X POST $HUB_HOST/login -o /dev/null

# 2. Backup ishga tushirish (server id=1)
curl -s -b /tmp/c -X POST $HUB_HOST/backups/run/1 | jq
```

#### Webhook test
```bash
TOKEN=$(grep WEBHOOK_TOKEN /opt/monitor-hub/.env | cut -d= -f2)
curl -X POST http://localhost:9991/webhook/$TOKEN \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test event",
    "body": "Webhook receiver test",
    "level": "info",
    "source": "manual"
  }'
```

## Authentication tafsilotlari

### Agent
```
Authorization: Bearer 64-character-hex-token
```
Token `/opt/monitor-agent/.agent-secret` faylida.

### Hub
- Login: `POST /login` form `username` + `password` → 302 redirect, cookie set
- Logout: `GET /logout`
- Sessiya: 7 kun (default)

### Webhook
- URL'da token: `/webhook/<token>`
- `WEBHOOK_TOKEN` env'da
- IP bo'yicha cheklov yo'q (kelajakda qo'shish mumkin)

## Status kodlari

| Kod | Ma'no |
|-----|-------|
| 200 | OK |
| 302 | Redirect (login muvaffaqiyatli) |
| 307 | Redirect (login kerak) |
| 400 | Yomon body (webhook yoki form xato) |
| 401 | Auth (agentda) |
| 404 | Topilmadi yoki webhook token noto'g'ri |
| 500 | Hub xatosi |

## Rate limiting

Hozircha yo'q. Agent va Hub'da rate limit qo'shish kelajakdagi reja.
