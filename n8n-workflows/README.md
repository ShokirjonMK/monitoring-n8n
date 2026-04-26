# n8n Workflows (qo'shimcha avtomatlashtirish)

monitor-hub o'zining scheduler'iga ega bo'lgani uchun **server monitoring**'i uchun bu workflow'lar **majburiy emas**.

Lekin shu fayllarni n8n'ga import qilib **qo'shimcha avtomatlashtirish**lar uchun ishlatishingiz mumkin (GitHub digest, custom integratsiyalar).

## Workflow'lar

| Fayl | Maqsad | Holat |
|------|--------|-------|
| `01-server-watchdog.json` | Container/endpoint/db nazorati | Hub tomonidan bajariladi → ixtiyoriy |
| `02-resource-alert.json` | Disk/RAM/load threshold | Hub tomonidan bajariladi → ixtiyoriy |
| `03-ssl-watcher.json` | SSL kun-qoldi | Hub tomonidan bajariladi → ixtiyoriy |
| `04-daily-backup.json` | Kunlik DB backup → Telegram | Hub tomonidan bajariladi → ixtiyoriy |
| `05-daily-digest.json` | Kunlik server hisoboti | Hub tomonidan bajariladi → ixtiyoriy |
| `06-github-tracker-daily.json` | **GitHub kunlik commit/PR digest** | ✅ tavsiya etiladi |
| `07-github-tracker-weekly.json` | **GitHub haftalik xulosa** | ✅ tavsiya etiladi |

> **Tavsiya:** 01-05 ni n8n'da **deactivate** qiling (Hub o'zi bajaradi).
> 06-07 (GitHub trackerlar) Hub'da yo'q — ularni saqlang.

## Talab qilinadigan environment variables

n8n'da `.env` faylga qo'shing:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
GITHUB_TOKEN=...
GITHUB_OWNER=ShokirjonMK    # yoki organizatsiya nomi

# Bu workflows monitoring uchun (agar ishlatsangiz)
MONITOR_SERVERS_JSON=[{"name":"main-uz","url":"http://172.17.0.1:9990","token":"<agent-token>"}]
```

## Import qilish

```bash
# n8n CLI orqali (n8n container ichida)
docker exec n8n n8n import:workflow --separate --input=/path/to/workflows/

# Activate qilish
docker exec n8n n8n update:workflow --id=<id> --active=true
docker compose restart n8n
```

Yoki n8n UI orqali: **Settings → Import from File**.

## GitHub tracker konfiguratsiyasi

`06-github-tracker-daily.json` ichida ("Per-Repo + Group" Code node):

```javascript
const customGroups = {
  'data-get': 'data',
  'kaos': 'kaos',
  'greenfin-uz': 'greenfin',
  'dissertation-reestr': 'dissertation',
  'devops-agent': 'devops',
};
const exclude = new Set([]);
```

O'zingizning loyihalaringizga moslang.

Default: repo nomidagi `-` belgisidan oldingi qism = guruh nomi.
- `sarbon-api` → "sarbon"
- `sarbon-front` → "sarbon"
- `data-get` → "data" (custom)

## Schedule

- 06: kunlik 09:00 (Asia/Tashkent)
- 07: dushanba 09:30 (Asia/Tashkent)

n8n'da `GENERIC_TIMEZONE=Asia/Tashkent` o'rnating.
