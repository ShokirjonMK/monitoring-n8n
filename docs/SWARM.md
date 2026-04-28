# Docker Swarm — nazorat va auto-scale

Hub Docker Swarm cluster'larni nazorat qiladi va xizmatlarni (services) yuklamaga
qarab avtomat ko'paytiradi/kamaytiradi.

## Imkoniyatlar

| Funksiya | Tafsilot |
|---|---|
| **Swarm aniqlash** | Har serverda `docker info` orqali swarm holati o'rganadi |
| **Service ro'yxati** | Manager node'larda service'lar, replicas, image, ports |
| **Node ro'yxati** | Cluster node'lari, status, availability |
| **Manual scale** | UI'da `+`/`−` tugmalar yoki to'g'ridan-to'g'ri replica soni |
| **Auto-scale rules** | Per-service CPU/Memory threshold asosida avtomat replicas |
| **Cooldown** | Flap'dan saqlash — har scale eventdan keyin minimum kutish |
| **Audit log** | Har scale (auto yoki manual) DB'da yoziladi |
| **Telegram alert** | Har scale event uchun (alert kanaliga) |

## Talablar

1. **Swarm initialized** kerak. Yangi serverda:
   ```bash
   sudo docker swarm init --advertise-addr <SERVER_IP>
   ```

2. Hub **manager node** bilan ishlaydi. Worker node'da service ro'yxati va scale operatsiyalari ishlamaydi (Docker'ning o'zi shunday cheklanadi).

3. Agent docker socket'ga ega bo'lishi kerak (default'da bor).

## Foydalanish

### 1) Swarm overview

Hub UI'da **Swarm** bo'limiga kiring (sidebar'da `bi-diagram-3` ikon).

Har server uchun karta ko'rsatiladi:
- 🟢 **manager** — service'larni boshqarish mumkin
- 🟠 **worker** — swarm a'zo lekin manager emas
- ⚪ **swarm yo'q** — `docker swarm init` qilinmagan

### 2) Service'larni boshqarish

Manager kartasida **"Service'lar →"** tugmasi → server detail sahifasi.

Bu yerda ko'rish mumkin:
- Barcha service'lar (mode, image, replicas, ports)
- Cluster node'lari
- Auto-scale rules holati
- So'nggi scale eventlar tarixi

### 3) Manual scale

Service yonidagi `−` va `+` tugmalar.
- `−` → 1 ga kamaytiradi
- `+` → 1 ga oshiradi
- O'rtadagi katta raqam — joriy desired replicas

Manual scale Telegram report kanaliga yuboriladi:
```
⚙️ Manual scale — main-uz
Service: api-backend
Replicas: 3 → 5
```

### 4) Auto-scale rule yaratish

Service qatoridagi **"Auto"** tugmasini bosing → rule formasi.

Maydonlar:

| Maydon | Default | Tavsif |
|---|---|---|
| **Metric** | `cpu` | CPU% yoki Memory% |
| **Scale UP threshold** | 70% | Bu qiymatdan oshsa replica qo'shadi |
| **Scale DOWN threshold** | 30% | Bu qiymatdan past bo'lsa replica kamaytiradi |
| **Min replicas** | 1 | Hech qachon shundan past tushmaydi |
| **Max replicas** | 10 | Hech qachon shundan oshmaydi |
| **Step** | 1 | Har bir scale eventda nechta replica qo'shadi/oladi |
| **Cooldown** | 300s | Eventdan keyin shu vaqt davomida hech qanday o'zgarish yo'q |
| **Faol toggle** | ON | O'chirilsa qoida saqlanadi lekin ishlamaydi |

**Saqlangandan so'ng** — Hub har 60 soniyada (watchdog interval) qoidani tekshiradi.

## Auto-scale qaror mantiqi

```
Har 60 soniyada (parallel hamma faol qoidalar):

   ┌─ Service'ning local replicas o'rtacha CPU/Mem o'lchanadi
   │
   ▼
   metric > scale_up_threshold ?
   │
   ├─ YES + replicas < max ?
   │       │
   │       ├─ Cooldown tugaganmi?
   │       │       │
   │       │       ├─ YES → "docker service scale name=N+step"
   │       │       │       Telegram: "📈 Auto-scale up: 3 → 4"
   │       │       │       last_scale_at = now
   │       │       │
   │       │       └─ NO → kutadi (cooldown ichida)
   │       │
   │       └─ Replicas yetdi (max) → kutadi
   │
   └─ NO → metric < scale_down_threshold ?
           │
           ├─ YES + replicas > min ?
           │       │
           │       └─ Cooldown tugaganmi?
           │             │
           │             ├─ YES → "docker service scale name=N-step"
           │             │       Telegram: "📉 Auto-scale down: 4 → 3"
           │             │
           │             └─ NO → kutadi
           │
           └─ NO → hech narsa qilmaydi
```

## Misol stsenariy

**Vaziyat:** `api-backend` service 3 replica bilan ishlamoqda. Foydalanuvchi tirbandligi oshib, CPU 85% ga yetdi.

**Rule:**
```
metric: cpu
scale_up_threshold: 70%
scale_down_threshold: 30%
min: 1, max: 10
step: 1
cooldown: 300s
```

**Vaqt jadvali:**
```
T+0       Hub o'lchadi: cpu=85% ≥ 70%
          Hub: docker service scale api-backend=4
          Telegram: "📈 api-backend: 3 → 4"
          last_scale_at = T+0

T+60      Hub o'lchadi: cpu=72% ≥ 70%
          Cooldown: 60s < 300s → kutadi

T+360     Hub o'lchadi: cpu=68% < 70% va > 30% → hech narsa

T+420     Hub o'lchadi: cpu=25% ≤ 30%, replicas=4 > 1
          Cooldown: 420s ≥ 300s → tugadi
          Hub: docker service scale api-backend=3
          Telegram: "📉 api-backend: 4 → 3"
```

## Eslatmalar va cheklovlar

### Local replica metric

Agent `docker stats` orqali **local node'dagi** task'larni o'lchaydi. Multi-node cluster'da:
- Agar service barcha node'larga tarqalgan bo'lsa, metric local replicas o'rtacha
- Cross-node aggregation hozir yo'q (Prometheus/cAdvisor integratsiyasi keyingi rejada)

### Manager only

Service ro'yxati va scale operatsiyalari **faqat manager** node'da ishlaydi. Agent worker node'ga o'rnatilgan bo'lsa, swarm sahifa ma'lumotni ko'rsatmaydi.

### Faqat replicated mode

`mode: global` service'lar uchun scale ma'no kasb etmaydi (har node'da 1 nusxa). Hub global service'lar uchun scale tugmalarini ko'rsatadi lekin ulardan foydalanmaslik kerak.

### Cluster auto-provisioning yo'q

Hub mavjud cluster ichida service replicas'ni o'zgartiradi. **Yangi node qo'shish** (cloud provider VM yaratish va swarm'ga qo'shish) hozir qo'llab-quvvatlanmaydi — bu cloud provider integratsiyasi (AWS/Hetzner/DigitalOcean API) talab qiladi va alohida moduldir.

Yangi node qo'lda qo'shish:
```bash
# Manager node'da
docker swarm join-token worker
# Yangi node'da chiqqan join komandasini ishga tushuring
```

## Telegram alert misollari

**Auto-scale up:**
```
📈 Auto-scale — main-uz
Service: api-backend
Replicas: 3 → 4
Sabab: cpu=85.2% >= 70.0%
```

**Auto-scale down:**
```
📉 Auto-scale — main-uz
Service: api-backend
Replicas: 4 → 3
Sabab: cpu=22.1% <= 30.0%
```

**Failed:**
```
⚠️ Auto-scale FAILED — main-uz
Service: api-backend (3 → 4)
Xato: rpc error: code = NotFound
```

## Auditing

`scale_event` jadvalida har scale yoziladi:

```
SELECT created_at, service_name, direction, from_replicas, to_replicas,
       triggered_by, ok, reason
FROM scaleevent
ORDER BY created_at DESC LIMIT 50;
```

UI'da Swarm detail sahifasining pastki qismida ko'rinadi.

## Troubleshooting

### "Bu node manager emas"

Agent worker node'da. Hub UI'da swarm overviewda 🟠 **worker** ko'rinadi. Service'larni boshqarish uchun manager node'ga ulaning yoki o'sha node'ni manager ga promote qiling:

```bash
docker node promote <NODE_ID>
```

### "Local replica yo'q"

Agent `docker stats` topa olmadi — service'ning task'lari shu node'da emas (multi-node cluster). Vaqtinchalik echim: kuzatishni service ko'p node'da bo'lgan node'ga ko'chiring.

### Auto-scale ishlamayapti

1. Rule **faol** ekanligini tekshiring (toggle ON)
2. Server **manager** ekanligini tekshiring
3. Hub log: `docker logs monitor-hub | grep autoscale`
4. Cooldown tugaganmi (`last_scale_at + cooldown_seconds < now`)
5. CPU thresholdga yaqin bo'lsa avval thresholdni biroz pasaytirib sinab ko'ring

### Service nomi to'g'rilanishi

`docker service ls` chiqishidagi nomni ishlating. Network'ga qarab to'liq nom bo'lishi mumkin (masalan `mystack_api`).

## Yangi talablar (kelajak)

- [ ] Prometheus metric source (cluster-wide CPU/mem)
- [ ] Cloud provider integration (AWS/Hetzner/DO) — node auto-provisioning
- [ ] Custom metric (Redis queue length, RPS, va h.k.) asosida scale
- [ ] Multi-rule (CPU OR memory)
- [ ] Schedule-based scale (kunduzi 5, kechasi 2)
