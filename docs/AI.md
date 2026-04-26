# AI integratsiyasi (multi-provider)

Hub har qanday AI provayderini qo'llab-quvvatlaydi. **BEPUL** variantlar ham bor:

| Provayder | Bepul limit | Sifat | Tezlik | Tavsiya |
|---|---|---|---|---|
| **Google Gemini** | 1500 req/kun, 15 RPM | ⭐⭐⭐⭐⭐ | tez | **#1 — eng yaxshi bepul** |
| **Groq** | 14400 token/min, 30 RPM | ⭐⭐⭐⭐ | ⚡ eng tez | tez ishlash uchun |
| **Cerebras** | 30 RPM | ⭐⭐⭐⭐ | ⚡⚡ super tez | minimum kechikish |
| **OpenRouter** | `:free` modellari | ⭐⭐⭐ | o'rta | turli modellarni sinash |
| **Anthropic Claude** | yo'q | ⭐⭐⭐⭐⭐ | tez | sifat zarur bo'lsa |
| **OpenAI** | yo'q | ⭐⭐⭐⭐⭐ | tez | GPT-4 zarur bo'lsa |
| **DeepSeek** | juda arzon | ⭐⭐⭐⭐ | tez | reasoning'i kuchli |
| **Custom** | — | — | — | Ollama, LM Studio, va h.k. |

## Tezkor boshlash — Gemini bilan (BEPUL, tavsiyam)

### 1-bosqich: API kalit yaratish

1. <https://aistudio.google.com/apikey> ga kiring (Google akkaunt kerak)
2. **"Create API key"** tugmasini bosing
3. Kalitni nusxalang (`AIzaSy...` bilan boshlanadi)

### 2-bosqich: Hub Sozlamalariga kiring

1. <http://YOUR_HUB:9991/settings>
2. AI bo'limiga o'ting
3. **Provayder:** `Google Gemini  (BEPUL — 1500 req/kun)` — default
4. **API kalit:** kalitni yopishtiring
5. **Model:** `Gemini 1.5 Flash (BEPUL, tez)` — default
6. **"Tokenni sinash"** tugmasi → ✓
7. **AI yoqilgan** toggle → Saqlash

Tamom! Endi AI har joyda ishlaydi.

---

## Boshqa BEPUL provayderlar

### Groq — eng tez Llama
- **Olish:** <https://console.groq.com/keys>
- **Limit:** 30 req/daqiqa, 14400 token/daqiqa
- **Modellar:** Llama 3.3 70B, Llama 3.1 70B, Mixtral 8x7B
- **Plus:** Dunyodagi eng tez LLM inference (mash'hur LPU asosida)

### OpenRouter — turli modellar
- **Olish:** <https://openrouter.ai/keys>
- **Limit:** Daily limits per :free model
- **Modellar (faqat `:free` bilan tugaganlari):**
  - `meta-llama/llama-3.3-70b-instruct:free`
  - `google/gemini-2.0-flash-exp:free`
  - `qwen/qwen-2.5-72b-instruct:free`
  - `microsoft/phi-3-medium-128k-instruct:free`
  - `nousresearch/hermes-3-llama-3.1-405b:free`

### Cerebras — super tez
- **Olish:** <https://cloud.cerebras.ai/platform>
- **Limit:** 30 req/daqiqa
- **Modellar:** Llama 3.3 70B, Llama 3.1 70B, Llama 3.1 8B
- **Plus:** Eng past kechikish (~100ms)

---

## Custom provayder (mahalliy yoki o'z endpoint)

OpenAI-compatible har qanday endpoint qo'llab-quvvatlanadi:

### Ollama (mahalliy LLM)
1. Ollama o'rnating: <https://ollama.com>
2. Model yuklang: `ollama pull llama3.1:8b`
3. Hub Sozlamalarda:
   - Provayder: **Custom (OpenAI-compatible)**
   - API kalit: `ollama` (har qanday qiymat — ollama tekshirmaydi)
   - Base URL: `http://172.17.0.1:11434/v1` (Docker'dan host'ga)
   - Model: `llama3.1:8b`

### LM Studio
- Local server boshlang
- Base URL: `http://172.17.0.1:1234/v1`
- API kalit: bo'sh yoki `lm-studio`

---

## AI har joyda ishlatiladigan funksiyalar

| Joy | Vazifa | UI |
|-----|--------|-----|
| **Sozlamalar** | Tokenni saqlashdan oldin sinash | "Tokenni sinash" tugmasi |
| **AI Yordamchi → Chat** | Erkin suhbat, server konteksti bilan | Tezkor tugmalar |
| **AI Yordamchi → Log tahlili** | Log paste → xato sabablari | Forma + Tahlil tugmasi |
| **Dashboard** | Fleet uchun bir martagi xulosa | "AI xulosa" tugmasi |
| **Server detail** | Bitta serverni batafsil tahlil | "AI tahlil" tugmasi |
| **Server detail → Alert** | Alert uchun aniq SSH/docker buyruqlar | Alert yonida "AI fix" |
| **Sozlamalar → Schedule** | Kunlik 08:00 hisobotni AI yozadi | "AI digest" toggle |

## Token narxi taxminan

| Operatsiya | Tokenlar | Gemini Free | Groq Free | OpenRouter :free |
|-----------|----------|------------|-----------|------------------|
| Token validate | ~50 | $0 | $0 | $0 |
| AI xulosa (3 server) | ~3000 | $0 | $0 | $0 |
| AI tahlil (1 server) | ~2500 | $0 | $0 | $0 |
| AI fix (1 alert) | ~2500 | $0 | $0 | $0 |
| Smart digest (1 server) | ~3000 | $0 | $0 | $0 |
| Daily digest (3 server) | ~10000 | **0/1500 req/kun** | **0** | **0** |

BEPUL provayder bilan: **kuniga 1500+ AI so'rov, mutlaqo bepul**.

## Provider ko'chish

Provayder o'zgartirish — Sozlamalardan boshqa provayderni tanlang, yangi API kalitni kiriting, sinash tugmasi → Saqlash. **Restart kerak emas.**

## Xavfsizlik

- API kalit DB'da plain text (`/app/data/hub.db`).
- Faqat container ichida — `data/` volume mount orqali host'da.
- Hub UI'da `password` input bilan ko'rinmaydi.
- **Server status JSON'i tanlangan provayderga yuboriladi** (faqat siz so'rasangiz):
  - Tarkibi: container nomlari, endpoint URL'lar, DB nomlari va o'lchamlar, disk/RAM/CPU
  - Tarkibsiz: parollar, kod, biznes ma'lumotlar
- Provayder o'zgarganda eski kalit DB'da saqlanmaydi (faqat yangisi).

## Troubleshooting

### "HTTP 401: Unauthorized"
- API kalit noto'g'ri yoki tugagan
- Provayder console'da kalit aktivmi tekshiring
- Hub'da provayderni to'g'ri tanlanganmi?

### "HTTP 429: Rate limit"
- Bepul tier limit'iga yetdingiz
- Bir oz kutib qayta urinib ko'ring
- Yoki boshqa provayderga (masalan, Groq → OpenRouter) o'tkazib turing

### "Model not found"
- Modelni boshqasi bilan almashtiring (dropdown'dan)
- Yoki: provayder console'da bu model ruxsat berilganmi tekshiring (ba'zi modellar yangi akkauntlar uchun yopiq)

### Custom (Ollama) javob bermayapti
- `docker logs monitor-hub | grep ollama` — Hub log
- Container'dan host'ga reachability: `docker exec monitor-hub curl http://172.17.0.1:11434`
- Ollama service ishlayotganini tekshiring: `systemctl status ollama` yoki `curl http://localhost:11434`
