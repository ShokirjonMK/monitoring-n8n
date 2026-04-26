# Texnik topshiriq — Multi-server monitoring tizimi

## 1. Loyiha maqsadi

Bir nechta serverlarda ishlovchi proyektlarni (containerlar, web ilovalar, ma'lumotlar bazalari) markaziy boshqaruv panelidan **doimiy nazorat qilish**, har qanday muammo aniqlanganda **zudlik bilan Telegram orqali ogohlantirish** va kunlik backuplarni avtomat olib borib, Telegram'ga yuborish.

Tizim **dinamik** bo'lishi kerak: yangi server qo'shish — config faylda yoki UI orqali bir necha qator bilan amalga oshadi, restart kerak emas.

## 2. Asosiy talablar

### 2.1. Universal admin panel
- [x] Web UI (login bilan)
- [x] Serverlar ro'yxati (CRUD: qo'shish, tahrirlash, o'chirish)
- [x] Live dashboard (har bir server uchun status kartochka)
- [x] Custom monitorlar (HTTP, TCP, SSL — har bir server uchun)
- [x] Alert tarixi
- [x] Backuplar (manual + automatic)
- [x] SSL/Domain nazorati
- [x] AI yordamchi (Claude bilan chat)
- [x] Sozlamalar (default Telegram, AI, scheduler intervals)

### 2.2. Doimiy monitoring
- [x] Har **60 soniyada** har bir serverning `/status` ma'lumotlarini olish
- [x] State diff: oldingi va hozirgi holatlar farqi
- [x] **Anti-flapping**: faqat 2 marta ketma-ket fail bo'lganda alert
- [x] Recovery xabari: muammo tugaganda yangilash
- [x] Threshold tekshiruvi (har 5 daqiqada): disk >80%, RAM >85%, load >5
- [x] SSL kunlik tekshiruv (06:00) — <14 kun bo'lsa alert

### 2.3. Per-server Telegram routing
- [x] Default kanal — global env (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`)
- [x] Server-level override:
  - `alert_bot_token` + `alert_chat_id` — kritik muammolar uchun
  - `report_bot_token` + `report_chat_id` — kunlik digest, backup natijasi
- [x] Bo'sh qoldirilsa → defaultga fallback
- [x] Chat turi: user / guruh / kanal (Telegram'da bot guruh/kanalga admin bo'lishi kerak)
- [x] Test tugmasi: ikki kanalga test xabar yuboradi

### 2.4. Alertlar va reportlar bo'linishi

| Turi | Kanal | Trigger |
|------|-------|---------|
| Container down/unhealthy | **alert** | watchdog tick |
| Endpoint timeout/HTTP xato | **alert** | watchdog tick |
| Database javob bermayapti | **alert** | watchdog tick |
| Resurs threshold buzilishi | **alert** | resource tick |
| SSL <14 kun | **alert** | daily 06:00 |
| Backup xato | **alert** | daily 02:00 |
| Backup muvaffaqiyat | **report** | daily 02:00 |
| Kunlik digest (server holati) | **report** | daily 08:00 |
| GitHub digest (commitlar) | **report** | daily 09:00 (n8n) |
| Webhook event (level=info) | **report** | external POST |
| Webhook event (level≥warning) | **alert** | external POST |

### 2.5. Maintenance mode
- [x] Server-level: `maintenance_until` datetime
- [x] Bu vaqt ichida monitoring davom etadi (state tracking)
- [x] Lekin Telegram alert yuborilmaydi
- [x] Maintenance tugaganda — yana ishlaydi

### 2.6. Alert lifecycle
1. **Detect** (1-tick): new failure → row insert, `consecutive_count=1`, `fired=false`
2. **Confirm** (2-tick): consecutive_count++, `>=CONFIRM_TICKS` → fire Telegram, `fired=true`
3. **Acknowledge**: admin "ack" qilsa → `acked_at` set
4. **Resolve**: holat OK ga qaytsa → `resolved_at` set, recovery alert
5. **Escalate** (kelajakda): 30 daqiqadan ortiq fired bo'lsa → kuchli kanal

### 2.7. AI yordamchi
- [x] Anthropic Claude API integratsiyasi
- [x] Suhbat tarixi (oxirgi 20 xabar)
- [x] Server status'ini kontekstga qo'shish opsiyasi
- [x] Tezkor tugmalar: "Tekshir", "Resurs xulosa"
- [x] Bir-marta xulosa: dashboard'dagi "AI xulosa" tugmasi

### 2.8. Backup
- [x] Har bir server'da `monitor-agent` `pg_dump` va `sqlite_copy` qila oladi
- [x] Daily 02:00 da Hub har bir aktiv serverga backup buyrug'i yuboradi
- [x] Natija fayllar `/backups/` ga gzip qilinib saqlanadi
- [x] 30 kunlik retention (eski fayllar avtomat o'chiriladi)
- [x] ≤50MB fayllar Telegram'ga yuboriladi (sendDocument)
- [x] >50MB lokal saqlanadi
- [x] Hub UI'dan ham manual ishga tushirish mumkin

## 3. Texnik arxitektura

### 3.1. monitor-agent (har serverda)
- Python + FastAPI
- Docker socket mount (`/var/run/docker.sock`)
- Host filesystem read-only mount (`/host` → `/proc`, sqlite copy uchun)
- Bearer token auth
- Endpointlar: `/health`, `/status`, `/containers`, `/resources`, `/endpoints`, `/databases`, `/ssl`, `/backup/run`, `/backup/list`, `/backup/file/{name}`, `/config`, `/reload`

### 3.2. monitor-hub (markaz)
- Python + FastAPI + SQLModel + Jinja2
- SQLite (config, alert tarix, AI suhbat tarixi)
- Background scheduler (asyncio): watchdog 60s, resource 300s, ssl/backup/digest cron
- Anthropic Claude SDK
- Session-based auth (cookie)
- Web UI (iOS-style)

### 3.3. n8n (qo'shimcha automation)
- Hub'sizga ham mustaqil monitoring workflow'lari (eski 7 ta)
- GitHub digest (kunlik 09:00, haftalik dushanba 09:30)
- Boshqa qo'shimcha avtomatlar (kelajakda)

## 4. Yangi server qo'shish

```bash
# 1. Yangi serverda agent
ssh new-server
sudo apt-get install docker.io  # if needed
mkdir -p /opt/monitor-agent && cd /opt/monitor-agent
# Clone monorepo or rsync from main
cp config.example.yml config.yml
nano config.yml          # endpoints, databases, backups, domains, thresholds
openssl rand -hex 32 > .agent-secret
docker compose up -d --build

# 2. Hub UI'da
# http://hub-host:9991 → Serverlar → Yangi
# Nomi: new-server
# Agent URL: http://NEW_IP:9990
# Token: <.agent-secret faylidan>
# (Ixtiyoriy) Alert/Report kanallari
# Saqlash → darhol monitoringga qo'shiladi
```

## 5. Webhook receiver

Tashqi servislar Hub'ga event yuborishi mumkin:

```bash
curl -X POST http://hub-host:9991/webhook/<TOKEN> \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Deploy failed",
    "body": "build #1234 failed",
    "level": "warning",
    "server": "main-uz",
    "source": "github-actions"
  }'
```

`level=info` → report kanaliga, `level=warning|critical` → alert kanaliga.

## 6. Xavfsizlik

- Agent: Bearer token (har serverda yagona)
- Hub: session cookie (admin parol, env'da)
- Webhook: yagona random token (env'da)
- AI API kalit: DB'da shifrlanadi (kelajakda)
- Telegram: bot token DB yoki env'da, plain text (Telegram tizimida boshqacha imkon yo'q)

## 7. Monitoring matritsasi

| Komponent | Tekshiruv chastotasi | Kanal | Anti-flapping |
|-----------|----------------------|-------|---------------|
| Agent reachability | 60s | alert | 2 tick |
| Container health | 60s | alert | 2 tick |
| Endpoint HTTP | 60s | alert | 2 tick |
| Database connect | 60s | alert | 2 tick |
| Disk usage | 5m | alert | 30 daq debounce |
| RAM usage | 5m | alert | 30 daq debounce |
| Load average | 5m | alert | 30 daq debounce |
| SSL expiry | 24h (06:00) | alert | — |
| Backup execution | 24h (02:00) | report (success) / alert (fail) | — |
| Daily digest | 24h (08:00) | report | — |

## 8. Performance va scaling

- 1 ta server: 1 watchdog tick = ~2-5s (status payload yuklanish)
- 10 ta server (parallel): ~3-8s (asyncio gather)
- 50 ta server: WATCHDOG_INTERVAL=120s tavsiya
- Hub o'zi yengil: ~50MB RAM, 1% CPU idle

## 9. Saqlash va arxiv

- SQLite: `/app/data/hub.db` (~5MB monthly)
- Backup files: `/app/backups/` (kuzatiladi 30 kun)
- AlertHistory: cheksiz (kelajakda 90 kunlik retention qo'shiladi)
- CheckRun (har tick logi): kelajakda 7 kunlik retention

## 10. Bajarilgan ishlar

- [x] FastAPI agent (9 endpoint)
- [x] FastAPI hub (Web UI + scheduler + AI)
- [x] SQLite migrations (idempotent)
- [x] Telegram routing (per-server override)
- [x] Smart alerting (state diff + anti-flapping)
- [x] Recovery alerts
- [x] Maintenance mode
- [x] Webhook receiver
- [x] Backup automation
- [x] SSL monitoring
- [x] AI chat (Claude)
- [x] iOS-style UI
- [x] Docker compose deployments

## 11. Kelajakdagi rejalar

- [ ] PostgreSQL ga ko'chirish (10+ server uchun)
- [ ] WebSocket live dashboard (auto-refresh siz)
- [ ] Grafana export (Prometheus metrics)
- [ ] Telegram inline acknowledge tugmasi
- [ ] AI auto-summary (kunlik xulosa, har soatlik anomaliya)
- [ ] Multi-tenant (bir nechta admin)
- [ ] CSV/JSON eksport (alert tarix)
- [ ] Custom dashboard widgets
