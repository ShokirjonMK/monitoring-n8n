# O'rnatish ko'rsatmasi

## Sistema talablari

- Linux (Ubuntu 22+/Debian 12+)
- Docker 24+
- Docker Compose v2
- Disk: 500MB (boshlang'ich) + backup hajmiga qarab
- RAM: Hub 100MB, har Agent 50MB
- Tarmoq: Hub har Agent'ga 9990 portda kirishi kerak

## Tezkor o'rnatish

### 1-bosqich: Repository klonlash

**Markaziy serverda (Hub uchun):**
```bash
git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
cd /opt/monitoring
```

### 2-bosqich: Har serverda Agent (eng tezkor — 1 qator)

```bash
curl -fsSL https://raw.githubusercontent.com/ShokirjonMK/monitoring-n8n/main/install.sh | bash
```

Skript:
1. Docker'ni tekshiradi
2. `/opt/monitor-agent` ga klonlaydi
3. `config.yml` ni minimal default bilan yaratadi
4. `.agent-secret` tokenini generatsiya qiladi
5. Container'ni ishga tushuradi
6. So'ngida **Hub'ga qo'shish ma'lumotlarini** chop etadi — nusxa olib formaga yopishtiring

### Qo'lda o'rnatish (skriptsiz)

```bash
git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
cd /opt/monitoring/monitor-agent
cp config.example.yml config.yml
nano config.yml   # qarang: docs/CONFIGURATION.md
openssl rand -hex 32 > .agent-secret
chmod 600 .agent-secret
docker compose up -d --build

# Tekshirish
curl http://localhost:9990/health
# {"status":"ok",...}

# Token (Hub'ga qo'shish uchun)
cat .agent-secret
```

### 3-bosqich: Markazda Hub

```bash
cd /opt/monitoring/monitor-hub
cp .env.example .env
nano .env

# Tahrirlang:
# ADMIN_PASS=<random_password>
# SECRET_KEY=<openssl rand -hex 24 chiqishi>
# TELEGRAM_BOT_TOKEN=<botning tokeni>
# TELEGRAM_CHAT_ID=<o'zingiz, guruh yoki kanal ID>
# WEBHOOK_TOKEN=<openssl rand -hex 24 chiqishi>

docker compose up -d --build

# Hub tayyor
curl http://localhost:9991/healthz
# {"status":"ok"}
```

### 4-bosqich: UI orqali server qo'shish

1. Brauzerda oching: `http://YOUR_HOST:9991`
2. Login: `admin` + sizning parol
3. **Serverlar → Yangi server**
4. To'ldiring:
   - Nomi: `main-uz` (yoki har qanday)
   - Agent URL: `http://172.17.0.1:9990` (lokal Docker bridge)
     yoki `http://NEW_SERVER_IP:9990` (boshqa hostda)
   - Agent token: 2-bosqichdagi `.agent-secret` qiymati
   - **Alert/Report kanallari** (ixtiyoriy):
     - Bo'sh qoldirilsa default kanaldan foydalaniladi
     - Boshqa bot/guruh kerak bo'lsa to'ldiring
5. Saqlash. Dashboard'da ko'rinadi (🟢 yoki 🔴).

### 5-bosqich: AI sozlash (ixtiyoriy)

1. **Sozlamalar** sahifasiga o'ting
2. Anthropic API kalitni kiriting (`sk-ant-...`)
3. Model: `claude-opus-4-7` (yoki ko'proq tezkor: `claude-haiku-4-5`)
4. "AI yoqilgan" toggle ni yoqing → Saqlash
5. **AI Yordamchi** sahifasidan chat boshlang

## n8n (ixtiyoriy)

GitHub digest va boshqa avtomatlar uchun:

```bash
cd /opt/monitoring/n8n-workflows
# README ichidagi yo'riqnomaga qarang
```

## Yangi server qo'shish (kelajakda)

1. Yangi server'da:
   ```bash
   git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
   cd /opt/monitoring/monitor-agent
   cp config.example.yml config.yml
   nano config.yml
   openssl rand -hex 32 > .agent-secret
   docker compose up -d --build
   cat .agent-secret  # nusxa oling
   ```
2. Hub UI'da:
   - **Serverlar → Yangi server** tugmasi
   - Ma'lumotlarni kiriting → Saqlash
3. Tamom — darhol monitoring boshlanadi.

## Telegram bot tayyorlash

### Bot yaratish
1. Telegram'da [@BotFather](https://t.me/BotFather) ga kiring
2. `/newbot` → nom bering
3. Token oling (`123456:ABC...`)
4. Tokenni `.env`'ga yozing

### Kanal/guruh ID olish
1. Botni kanal/guruhga **admin sifatida** qo'shing
2. Kanalga test xabar yuboring (yoki `/start` botga)
3. Brauzerda oching:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. JSON ichida `chat.id` ni toping
   - User: `813225336`
   - Group: `-100123456789`
   - Channel: `-1001234567890`

### Test
Hub UI'da server detail sahifasida "**Kanallarni sinash**" tugmasi.

## Mainenance mode

Rejalashtirilgan ish davomida alertlarni o'chirish:

1. Server tahrirlash sahifasi
2. **Maintenance until** maydoniga vaqt kiriting (UTC)
3. Saqlash
4. Bu vaqtgacha:
   - Status holatlari hisobga olinadi (kuzatish davom etadi)
   - Telegram alert yuborilmaydi
5. Vaqt o'tgach avtomat normallashadi

## Troubleshooting

### Agent javob bermayapti
```bash
# Agent log
docker logs monitor-agent --tail 50

# Direct probe
curl http://AGENT_IP:9990/health

# Token tekshirish
TOKEN=$(cat /opt/monitor-agent/.agent-secret)
curl -H "Authorization: Bearer $TOKEN" http://localhost:9990/status | head
```

### Hub Telegram yubormayapti
```bash
# Hub log
docker logs monitor-hub | grep -i telegram

# Bot tokenni qo'lda test qilish
curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
  -d "chat_id=<CHAT>" -d "text=test"
```

### Migration xatolari
```bash
# Hub DB ni reset qilish
docker compose down
rm -rf /opt/monitor-hub/data/hub.db*
docker compose up -d --build
```

### Container "0/N" — Docker socket
Agent `docker ps` ishlamasligi:
```bash
ls -la /var/run/docker.sock
# Kerakli: srw-rw---- 1 root <docker-group> ...
```

Agent'ni rebuild qiling — yangi versiyada static docker CLI binary kelishi kerak.

## Yangilash

```bash
cd /opt/monitoring
git pull
cd monitor-agent && docker compose up -d --build
cd ../monitor-hub && docker compose up -d --build
```

`hub.db` saqlanib qoladi (volume mount).

## Backup'lar

- Lokal: `/opt/monitor-agent/backups/` (har serverda)
- Telegram: ≤50MB fayllar avtomat yuboriladi
- Manual download: Hub UI → Server Detail → Backuplar bo'limi
- Retention: `config.yml` da `backup_retention_days: 30`
