# 🛰 Monitoring Stack

Multi-server nazorat tizimi. Har bir serverdagi containerlar, endpointlar, ma'lumotlar bazalari, SSL sertifikatlar va kunlik backuplarni avtomat kuzatadi va Telegram'ga ogohlantirish yuboradi.

## Komponentlar

| Komponent | Vazifa | Texnologiya | Port |
|-----------|--------|-------------|------|
| **monitor-agent** | Har bir serverda turadi, JSON status beradi | FastAPI + Docker socket | 9990 |
| **monitor-hub** | Markaziy boshqaruv paneli + scheduler | FastAPI + SQLite + Jinja2 | 9991 |
| **n8n-workflows** | Avtomatlashtirilgan workflow'lar (qo'shimcha) | n8n | 5678 |

## Asosiy xususiyatlar

### Monitoring
- ✅ **Doimiy nazorat** — har 60s status tekshiruv (sozlanadi)
- ✅ **Smart alerting** — anti-flapping (2 marta tasdiqlanguncha tindiriladi)
- ✅ **Recovery alerts** — muammo tugaganda xabar
- ✅ **Resurs threshold** — disk/RAM/load >threshold da alert (debounce bilan)
- ✅ **SSL nazorat** — sertifikat tugashidan 14 kun oldin alert
- ✅ **Backup automation** — kunlik dump → Telegram yoki lokal
- ✅ **Status timeline** — har server uchun so'nggi 40 ta tick (yashil/sariq/qizil bar)

### Telegram routing
- ✅ **Per-server bot/chat** — har server o'z kanaliga
- ✅ **Default kanal admin paneldan** — env'siz, UI orqali boshqarish
- ✅ **Alert vs Report kanallari** — kritik va digestlar alohida
- ✅ **"Kanallarni topish"** tugmasi — `getUpdates` orqali avtomat
- ✅ **Test tugmasi** — saqlashdan oldin sinab ko'rish
- ✅ **Maintenance mode** — rejalashtirilgan ish vaqtida alertlar tindiriladi

### AI (Claude)
- ✅ **Token validate** tugmasi — saqlashdan oldin tekshirish
- ✅ **AI chat** — server status kontekstida
- ✅ **AI xulosa** (Dashboard) — fleet uchun bir martagi tahlil
- ✅ **AI tahlil** (Server detail) — bitta server uchun batafsil
- ✅ **AI fix** (Alert yonida) — alert uchun aniq SSH/docker buyruqlar
- ✅ **Log tahlili** — log paste qiling, xato sabablari
- ✅ **Smart digest** — Claude tomonidan yozilgan kunlik hisobot

### Boshqaruv
- ✅ **Wizard bilan server qo'shish** — bir qator install skript
- ✅ **Aloqa probe** — saqlashdan oldin agent javob berishini tekshirish
- ✅ **Manual triggerlar** — Dashboard'dan "Hammasi" yoki har biriga alohida
- ✅ **Schedule UI'dan** — interval/vaqt/toggle barchasi DB'da
- ✅ **Webhook receiver** — tashqi servislar event yuborishi mumkin
- ✅ **Alert acknowledgement** — ko'rilganini belgilash
- ✅ **Recent activity** — har server uchun 24 soat tarixi

## Tezkor boshlash

### Agent (har serverda) — 1 qator buyruq

```bash
curl -fsSL https://raw.githubusercontent.com/ShokirjonMK/monitoring-n8n/main/install.sh | bash
```

Skript Docker'ni tekshiradi, kodni yuklaydi, container ishga tushiradi va so'ngida **Hub'ga qo'shish uchun ma'lumotlarni** chop etadi (URL + Token).

### Hub (markazda) — bir martalik

```bash
git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
cd /opt/monitoring/monitor-hub
cp .env.example .env
nano .env                # ADMIN_PASS, SECRET_KEY (Telegram va boshqalarni admin paneldan kiriting)
docker compose up -d --build
```

So'ngra `http://YOUR_HOST:9991` → login → Sozlamalar → Telegram bot tokenni va chat ID'larni kiriting (`Kanallarni topish` tugmasi yordam beradi).

### Server qo'shish (UI'da)
1. **Serverlar → Yangi server** → Wizard ko'rinadi
2. Wizard buyruqni nusxalab yangi serverda ishga tushiring
3. Skript chiqargan ma'lumotlarni formaga yopishtiring
4. **"Aloqani sinash"** tugmasi bilan tekshiring → yashil bo'lsa Saqlash

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
