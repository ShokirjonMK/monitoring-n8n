# Konfiguratsiya

## monitor-agent — `config.yml`

Bitta `config.yml` har serverda turadi va shu server haqidagi barcha narsani belgilaydi.

```yaml
server_name: main-uz   # log va xabarlarda ko'rinadi

# HTTP healthcheck — har bir endpoint
endpoints:
  - name: DataGate                          # ko'rinadigan nom
    url: http://172.17.0.1:5000/login       # to'liq URL (Docker bridge IP yoki domen)
    expect: 200                              # status code yoki list [200, 301, 302]
    method: GET                              # default GET (POST/PUT ham mumkin)
  - name: Backend
    url: http://api.example.com/health
    expect: [200, 204]                      # bir nechta qabul qilinadigan kod

# Ma'lumotlar bazalari
databases:
  - name: app_db
    type: postgres
    container: app-postgres                  # docker exec ishlatadi
    db: app
    user: app_user
  - name: cache
    type: sqlite
    path: /opt/app/data/cache.db             # host filesystem (mounted /host)

# Backuplar
backups:
  - name: app_db
    type: pg_dump                            # docker exec → pg_dump → gzip
    container: app-postgres
    db: app
    user: app_user
  - name: cache_db
    type: sqlite_copy                        # gzip qilingan SQLite faylni copy
    path: /opt/app/data/cache.db
  - name: uploads
    type: directory                          # tar.gz papka
    path: /opt/app/uploads

backup_retention_days: 30                    # eskilarini avtomat o'chirish

# SSL nazorat
domains:
  - {host: example.com, port: 443}
  - {host: api.example.com, port: 443}
  - {host: legacy.example.com, port: 8443}

# Threshold qiymatlari (default)
thresholds:
  disk_pct: 80     # disk band foizi
  mem_pct: 85      # RAM band foizi
  load_1m: 5.0     # load average 1 daqiqa
```

### Config qayta yuklash (restartsiz)

```bash
TOKEN=$(cat /opt/monitor-agent/.agent-secret)
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:9990/reload
```

## monitor-hub — `.env`

```env
# Web UI
ADMIN_USER=admin
ADMIN_PASS=<random>
SECRET_KEY=<openssl rand -hex 24>
LOG_LEVEL=INFO

# Default Telegram (server-level override yo'q bo'lganda)
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<user/group/channel id>

# Ixtiyoriy: alertlar va reportlar uchun alohida default chat
TELEGRAM_ALERT_CHAT_ID=
TELEGRAM_REPORT_CHAT_ID=

# Continuous monitoring
HUB_SCHEDULER_ENABLED=true
WATCHDOG_INTERVAL=60       # sekund (har bir serverdan /status olish)
RESOURCE_INTERVAL=300      # sekund (resurs threshold tekshiruv)
CONFIRM_TICKS=2            # nechta consecutive bad ticks dan keyin alert

# Webhook receiver
WEBHOOK_TOKEN=<openssl rand -hex 24>
```

## Hub UI orqali sozlamalar

### Server qo'shish/tahrirlash sahifasi

| Maydon | Majburiy | Tavsif |
|--------|----------|--------|
| Nomi | ✓ | yagona, qisqa identifikator |
| Agent URL | ✓ | `http://IP:9990` |
| Agent token | ✓ | `.agent-secret` qiymati |
| Tavsif | — | qo'shimcha izoh |
| Faollik toggle | — | o'chirilsa nazoratsiz |
| **Alert bot token** | — | bo'sh bo'lsa default |
| **Alert chat ID** | — | bo'sh bo'lsa default |
| **Report bot token** | — | bo'sh bo'lsa default |
| **Report chat ID** | — | bo'sh bo'lsa default |
| Maintenance until | — | bu vaqtgacha alert tindiriladi (UTC) |

### Sozlamalar sahifasi

- **Anthropic API kalit** — AI yordamchi uchun
- **Model** — Opus 4.7 / Sonnet 4.6 / Haiku 4.5
- **System prompt** — AI'ning xulq-atvori, tilini belgilaydi
- **AI yoqilgan toggle**

## Telegram chat turlari

| Turi | ID format | Qanday olinadi |
|------|-----------|----------------|
| User | `123456789` (musbat) | `getUpdates` orqali botga xabar yuborib |
| Group | `-100123456789` (manfiy) | botni guruhga admin qilib qo'yib + xabar |
| Channel | `-1001234567890` (manfiy) | botni kanalga admin qilib qo'yib |

> **Muhim:** bot guruh/kanalga admin qilinmasa, xabar yubora olmaydi.

## Threshold sozlamalari

`config.yml` ichidagi `thresholds:` har server uchun alohida:

```yaml
thresholds:
  disk_pct: 80     # 80% dan oshsa disk alert
  mem_pct: 85      # RAM alert
  load_1m: 5.0     # CPU yuk alert (1m avg)
```

Default qiymatlarni o'zgartirib qayta yuklang (`/reload`).

## Webhook receiver

Tashqi servis Hub'ga event yuborish:

```bash
curl -X POST http://hub-host:9991/webhook/<WEBHOOK_TOKEN> \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Build failed",
    "body": "main branch test_auth.py failed",
    "level": "warning",
    "server": "main-uz",
    "source": "github-actions"
  }'
```

Routing:
- `level=info` → report kanaliga
- `level=warning` yoki `critical` → alert kanaliga
- `server` ko'rsatilsa — server'ning per-server kanaliga
- `server` yo'q bo'lsa — global default kanalga

## Misol: server uchun guruh kanali

1. Telegram'da yangi guruh yarating (masalan "Server Alerts")
2. Botni admin qilib qo'shing (`@mkdevbackupbot`)
3. Bot'dan `/start` chiqaring (yoki test xabar)
4. Brauzerda: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. JSON ichida `chat.id` ni toping (manfiy son)
6. Hub UI'da Server tahrirlash → **Alert chat ID**'ga yozing
7. Saqlash → **Kanallarni sinash** tugmasi → ✓

Endi shu serverning barcha alertlari faqat shu guruhga ketadi.

## Misol: kompaniya kanali

Bir nechta server uchun bitta kanal:

```env
# Hub .env
TELEGRAM_BOT_TOKEN=<global bot>
TELEGRAM_ALERT_CHAT_ID=-1001234567890  # company-alerts kanal
TELEGRAM_REPORT_CHAT_ID=-1009876543210  # company-reports kanal
```

Yoki har serverga alohida override qo'ying — moslashuvchan.
