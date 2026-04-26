# 🛰 Monitoring Stack

Multi-server nazorat tizimi. Har bir serverdagi containerlar, endpointlar, ma'lumotlar bazalari, SSL sertifikatlar va kunlik backuplarni avtomat kuzatadi va Telegram'ga ogohlantirish yuboradi.

## Komponentlar

| Komponent | Vazifa | Texnologiya | Port |
|-----------|--------|-------------|------|
| **monitor-agent** | Har bir serverda turadi, JSON status beradi | FastAPI + Docker socket | 9990 |
| **monitor-hub** | Markaziy boshqaruv paneli + scheduler | FastAPI + SQLite + Jinja2 | 9991 |
| **n8n-workflows** | Avtomatlashtirilgan workflow'lar (qo'shimcha) | n8n | 5678 |

## Asosiy xususiyatlar

- ✅ **Doimiy monitoring** — har 60s status tekshiruv
- ✅ **Smart alerting** — anti-flapping (2 marta tasdiqlanguncha tindiriladi)
- ✅ **Recovery alerts** — muammo tugaganda xabar
- ✅ **Per-server Telegram routing** — har server o'z bot/chat'ini belgilaydi
- ✅ **Alert vs Report kanallari** — kritik xatolar va kunlik digestlar alohida kanalda
- ✅ **Maintenance mode** — rejalashtirilgan ish vaqtida alertlar tindiriladi
- ✅ **AI yordamchi** — Claude bilan chat (server status'ini kontekst sifatida)
- ✅ **Dinamik server qo'shish** — UI orqali, restart kerak emas
- ✅ **Backup automation** — kunlik dump → Telegram (≤50MB) yoki lokal
- ✅ **SSL nazorat** — sertifikat tugashidan 14 kun oldin alert
- ✅ **Webhook receiver** — tashqi servislar event yuborishi mumkin
- ✅ **Acknowledgement** — alert ko'rilganini belgilash

## Tezkor boshlash

```bash
# 1. Har bir serverga monitor-agent o'rnatish
cd monitor-agent
cp config.example.yml config.yml
# config.yml ni tahrirlang — kuzatiladigan endpointlar, bazalarni qo'shing
openssl rand -hex 32 > .agent-secret
docker compose up -d --build

# 2. Markaziy serverga monitor-hub o'rnatish
cd ../monitor-hub
cp .env.example .env
# .env ni tahrirlang: ADMIN_PASS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
docker compose up -d --build

# 3. Hub UI'da serverni qo'shish
# http://localhost:9991 → login → Serverlar → Yangi
```

To'liq qo'llanma: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## Hujjatlar

- [`docs/TZ.md`](docs/TZ.md) — texnik topshiriq, talablar
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — tizim arxitekturasi
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — o'rnatish ko'rsatmasi
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — barcha sozlamalar
- [`docs/API.md`](docs/API.md) — agent va hub HTTP API
- [`docs/TELEGRAM.md`](docs/TELEGRAM.md) — Telegram routing va kanallar

## Litsenziya

MIT.
