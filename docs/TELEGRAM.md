# Telegram routing va kanallar

Tizim har bir serverning **alertlari** va **reportlari** uchun alohida Telegram kanali sozlash imkonini beradi.

## Kanal turlari

### Alert kanali
- Kritik muammolar uchun
- Anti-flapping bilan (2 ta consecutive bad ticksdan keyin)
- Recovery ham shu yerga (rang yashil)

### Report kanali
- Kunlik digest, backup natijasi, info xabarlar
- Spam emas — ortiqcha shovqin yo'q

### Default kanal
- Hub `.env`'dagi `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- Per-server override yo'q bo'lganda ishlatadi

## Routing mantiqi

```
Hub muammoli holatni topdi (server X, container nginx down)
         │
         ▼
resolve_alert_channel(server_X)
         │
         ├─ server_X.alert_bot_token va alert_chat_id mavjudmi?
         │       └─ Ha → o'sha bot, o'sha chat'ga
         │
         └─ Yo'q → default
                  ├─ TELEGRAM_ALERT_CHAT_ID env mavjudmi?
                  │       └─ Ha → TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID
                  └─ Yo'q → TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
         │
         ▼
HTTP POST → api.telegram.org/bot<TOKEN>/sendMessage
```

Resolve_report_channel ham xuddi shunday — `report_*` o'zgaruvchilari bilan.

## Misol stsenariylar

### 1) Bitta kompaniya, hammasi bitta chatga

```env
# .env
TELEGRAM_BOT_TOKEN=8059993248:AAxxx
TELEGRAM_CHAT_ID=813225336      # admin user
```
Server-level override yo'q. Hammasi `813225336` ga ketadi.

### 2) Alertlar va reportlar alohida

```env
TELEGRAM_BOT_TOKEN=8059993248:AAxxx
TELEGRAM_CHAT_ID=813225336              # backward compat
TELEGRAM_ALERT_CHAT_ID=-1001111111111   # urgent group
TELEGRAM_REPORT_CHAT_ID=-1002222222222  # daily reports group
```

### 3) Har bir mijozga alohida kanal

```
Server "client-acme":
  alert_bot_token  = (default — bo'sh)
  alert_chat_id    = -1003333333333  (acme alerts kanal)
  report_bot_token = (default)
  report_chat_id   = -1003333333334  (acme reports kanal)

Server "client-bigco":
  alert_bot_token  = 9999:DIFF       (boshqa bot — masalan kompaniya brendi)
  alert_chat_id    = -1004444444444
  report_bot_token = 9999:DIFF
  report_chat_id   = -1004444444445
```

### 4) Faqat alerts uchun ko'p kanal, reports markazda

```
Server #1: alert override → ProjectA group
Server #2: alert override → ProjectB group
Server #3: alert override → ProjectC group
(reports overrides yo'q → hammasi default'ga)
```

## Bot tayyorlash

### 1. Bot yaratish
```
Telegram → @BotFather → /newbot
  → Nom: "MyCompany Monitor"
  → Username: "mycompany_monitor_bot"
  → Token: 1234567890:ABCdefGhI...
```

### 2. Chat ID olish

#### User chat
```
1. Telegram'da bot bilan suhbat boshlang (/start)
2. Brauzerda: https://api.telegram.org/bot<TOKEN>/getUpdates
3. message.chat.id ni toping (musbat son)
```

#### Group chat
```
1. Yangi guruh yarating
2. Botni a'zo qiling
3. Botni ADMIN qiling (Aks holda u faqat o'zining xabarini ko'radi)
4. Guruhga test xabar yuboring
5. https://api.telegram.org/bot<TOKEN>/getUpdates
6. message.chat.id (manfiy son, -100 dan boshlanadi)
```

#### Channel
```
1. Yangi kanal yarating
2. Botni admin sifatida qo'shing (post huquqi bilan)
3. Kanalga test xabar (bot orqali yuborib ko'ring)
4. https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=@channel_username&text=test
   yoki ID format: -100xxxxxxxxxx
```

### 3. Kanalni Hub'ga qo'shish

#### Default sifatida
`.env` faylga yozing:
```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```
`docker compose up -d` qiling.

#### Server-level override
1. Hub UI'da server tahrirlash sahifasi
2. Pastki qismida "Telegram alert kanali" bloki
3. Bot token va chat ID kiriting
4. Saqlash → "Kanallarni sinash" tugmasi

## Anti-spam mexanizmlari

| Mexanizm | Maqsad |
|----------|--------|
| Anti-flapping | 2 marta consecutive bad ticks dan keyin alert |
| Threshold debounce | Resurs alertlari 30 daq oraliqda qaytarilmaydi |
| Recovery deduplication | Resolved alert qayta ko'tarilsa, yangi tarixda boshlanadi |
| Maintenance suppression | Belgilangan vaqt ichida hech qanday alert yuborilmaydi |
| Acknowledgement | Admin "ack" qilsa keyingi takroriy yangilanish bo'lmaydi |

## Webhook orqali tashqi alertlar

Tashqi servis sizga event yuborish uchun:

```bash
curl -X POST http://hub:9991/webhook/<TOKEN> \
  -H "Content-Type: application/json" \
  -d '{
    "title": "GitHub: Deploy failed",
    "body": "Workflow #1234 failed at step \"Tests\"",
    "level": "warning",
    "server": "main-uz",          // optional
    "source": "github-actions"
  }'
```

`level` ga qarab routing:
- `info` → report kanali
- `warning` → alert kanali
- `critical` → alert kanali (kelajakda escalation level)

## Diagnostika

### Telegram'ga yetib bormayapti

```bash
# 1. Bot ishlaydimi?
curl https://api.telegram.org/bot<TOKEN>/getMe

# 2. Bot guruh/kanalga admin emasmi? Yoki user bot bilan /start qilmaganmi?
curl https://api.telegram.org/bot<TOKEN>/sendMessage \
  -d chat_id=<CHAT> -d text=test

# 3. Hub log tekshiruvi
docker logs monitor-hub | grep -i telegram | tail
```

### Test message yuborish

Hub UI → Server detail (Tahrirlash) → "Kanallarni sinash" tugmasi.
Yoki:
```bash
curl -b /tmp/cookies -X POST http://hub:9991/servers/1/test-channels
```

## Best practices

1. **Alert kanali = alohida guruh** — qisqa, urgent xabarlar uchun
2. **Report kanali = boshqa guruh yoki admin user** — kunlik digest, batafsil ma'lumotlar
3. **Per-server override** — yiriklashayotgan tashkilotlar uchun (har mijozga alohida)
4. **Maintenance mode** ishlating — rejalashtirilgan ish davomida Telegram chatni shovqindan saqlash uchun
5. **Bot tokenni qayta ishlating** — har server uchun yangi bot kerak emas (chat_id farq qiladi)
