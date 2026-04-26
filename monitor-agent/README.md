# monitor-agent

Server-resident agent. Bitta server haqida JSON ko'rinishida ma'lumot beruvchi yengil FastAPI servis.

## Tezkor o'rnatish

```bash
git clone https://github.com/ShokirjonMK/monitoring-n8n.git /opt/monitoring
cd /opt/monitoring/monitor-agent

# Konfiguratsiya
cp config.example.yml config.yml
nano config.yml          # endpointlar, DB'lar, backuplar, SSL domens

# Yagona token
openssl rand -hex 32 > .agent-secret
chmod 600 .agent-secret

# Ishga tushirish
docker compose up -d --build

# Tekshirish
curl http://localhost:9990/health
```

## Endpointlar

| Path | Method | Auth | Maqsad |
|------|--------|------|--------|
| `/health` | GET | yo'q | Yashash ko'rsatkichi |
| `/status` | GET | bearer | Hammasi (containers + resources + endpoints + DBs) |
| `/containers` | GET | bearer | Faqat containerlar |
| `/resources` | GET | bearer | Disk/RAM/load |
| `/endpoints` | GET | bearer | HTTP probe natijasi |
| `/databases` | GET | bearer | DB connect status |
| `/ssl?host=X&port=443` | GET | bearer | Bitta domen |
| `/ssl/all` | GET | bearer | Configdagi domenlar |
| `/backup/run` | POST | bearer | Backup ishga tushirish |
| `/backup/list` | GET | bearer | Saqlangan fayllar |
| `/backup/file/{name}` | GET | bearer | Stream download |
| `/config` | GET | bearer | Joriy config |
| `/reload` | POST | bearer | config.yml qayta o'qish |

To'liq batafsil: [`docs/API.md`](../docs/API.md).

## Xavfsizlik

- Bearer token (`/opt/monitor-agent/.agent-secret`)
- 600 permissions (faqat egasi o'qiy oladi)
- Token tashqi tarmoqqa chiqmasligi kerak — Hub bilan yopiq tarmoqda gaplashing

## Mounts

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock   # docker ps, docker exec
  - /:/host:ro                                   # /proc, sqlite copy
  - ./config.yml:/app/config.yml:ro
  - ./backups:/backups
```

> **Diqqat:** `/:/host:ro` — host filesystem'ni read-only mount qiladi. Ag-tashqi serverlarda
> bu xavfsizlik nuqtai nazaridan yuqori. Agar minimallik kerak bo'lsa, faqat `/proc` va kerakli yo'llarni mount qiling.

## Yangi proyekt qo'shish

`config.yml` ni tahrirlang:
```yaml
endpoints:
  - {name: "Yangi servis", url: "http://172.17.0.1:9000/health", expect: 200}

databases:
  - {name: yangi_db, type: postgres, container: yangi-postgres, db: app, user: postgres}
```

So'ng restartsiz qayta yuklash:
```bash
TOKEN=$(cat .agent-secret)
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:9990/reload
```

## Loglar

```bash
docker logs monitor-agent --tail 50 -f
```
