# AI (Claude) integratsiyasi

Hub Anthropic Claude bilan integrlashgan. AI quyidagi joylarda yordam beradi:

| Joy | Vazifa |
|-----|--------|
| **Sozlamalar** sahifasi | Tokenni saqlashdan oldin sinash |
| **AI Yordamchi** sahifasi (Chat) | Erkin suhbat, server konteksti bilan |
| **AI Yordamchi** sahifasi (Log tahlili) | Log paste → xato sabablari |
| **Dashboard** "AI xulosa" tugmasi | Butun fleet bo'yicha bir martagi xulosa |
| **Server detail** "AI tahlil" tugmasi | Bitta serverni batafsil tahlil + tavsiyalar |
| **Alert yonida** "AI fix" tugmasi | Alert uchun aniq SSH/docker buyruqlari |
| **Sozlamalar → Schedule** "AI digest" toggle | Kunlik 08:00 hisobotni AI yozadi |

## Token o'rnatish (1 daqiqa)

1. **API kalit yaratish:**
   - [console.anthropic.com → Settings → API Keys](https://console.anthropic.com/settings/keys)
   - "Create Key" tugmasi
   - Nom bering (masalan: `monitor-hub`)
   - Kalitni nusxalang (qaytib ko'rsatilmaydi)

2. **Hub Sozlamalariga kiring:**
   - <http://YOUR_HUB:9991/settings>
   - "Anthropic API kalit" maydoniga yopishtiring

3. **Tokenni sinash:**
   - "Tokenni sinash" tugmasi → Anthropic'ga kichik test so'rovi yuboriladi
   - Yashil bo'lsa — kalit ishlaydi
   - Qizil bo'lsa — xato sababi ko'rsatiladi (auth, model topilmadi, billing, va h.k.)

4. **Modelni tanlang:**
   - **Haiku 4.5** — eng tez/arzon (~$0.30/M input tokens)
   - **Sonnet 4.6** — balanced (~$3/M input tokens)
   - **Opus 4.7** — eng kuchli (~$15/M input tokens, server tahlili uchun ortiqcha bo'lishi mumkin)
   - Tavsiya: kundalik foydalanish uchun **Haiku**, batafsil tahlil uchun **Sonnet/Opus**

5. **AI yoqing:**
   - "AI yoqilgan" toggle → Saqlash

## Foydalanish stsenariylari

### 1) Server haqida tezkor xulosa
Dashboard sahifasida → "AI xulosa" tugmasi.
Hammasiga umumiy 5-jumla xulosa, anomaliyalar belgilanadi.

### 2) Bitta serverni batafsil tahlil
Serverlar → server tanlang → **AI tahlil** tugmasi.
Claude:
- Umumiy baho (yashil/sariq/qizil)
- Muammoli komponentlar va sabablari
- Tuzatish uchun aniq buyruqlar
- Keyingi 24 soatda nimani kuzatish kerak

### 3) Alert uchun fix tavsiyalari
Server detail → Recent activity → har bir alert yonida **AI fix** tugmasi.
Claude alert + hozirgi serverni ko'rib, aniq diagnostika va tuzatish ketma-ketligini beradi.

### 4) Log tahlili
AI Yordamchi → Log tahlili tabi.
Container logini paste qiling (`docker logs ...`), kontekst yozing — Claude xato sabablari va keyingi qadamlarni aytib beradi.

### 5) AI tomonidan kunlik digest
Sozlamalar → Schedule → "AI digest" toggle.
Yoqilsa — kunlik 08:00 hisobotni Claude yozadi (templated o'rniga). HTML formatida, qisqartirilgan, e'tibor qaratiladigan narsalar alohida belgilanadi.

### 6) Erkin chat
AI Yordamchi → Chat tabi. Server konteksti checkbox bilan qo'shiladi (default ON).
Misol so'rovlar:
- "Hozir nima holatda? Diqqat qiluvchi narsalar bormi?"
- "Disk va RAM ishlatilishi haqida xulosangiz?"
- "Backup strategiyasi haqida tavsiya bering"
- "datagate container nega restart bo'ldi? logs haqida nima deyish mumkin?"

## Token narxi taxminan

| Operatsiya | Tokenlar (taxminan) | Haiku narxi |
|-----------|---------------------|-------------|
| Token validate | ~50 | ~$0.00002 |
| AI xulosa (fleet, 3 server) | ~3000 input + 300 output | ~$0.001 |
| AI tahlil (1 server) | ~2000 input + 500 output | ~$0.001 |
| AI fix (1 alert) | ~2500 input + 600 output | ~$0.001 |
| Smart digest (1 server) | ~2500 input + 500 output | ~$0.001 |
| Log analizi (1KB log) | ~1000 input + 400 output | ~$0.0006 |
| Daily digest (3 server, AI) | ~7500 input + 1500 output | ~$0.003 |

Kuniga ~$0.10 dan kam (Haiku bilan, 3 server, ko'p AI ishlatish bilan).

## Xavfsizlik

- API kalit DB ichida plain-text saqlanadi (`/app/data/hub.db`).
- Faqat container ichida — `data/` volume mount'i orqali host'da saqlanadi.
- Hub UI'da `password` input bilan ko'rinmaydi.
- **Server status JSON'i Anthropic'ga yuboriladi** (faqat siz so'rasangiz).
   - Tarkibi: container nomlari, endpoint URL'lar, DB nomlari va o'lchamlar, disk/RAM/CPU statistikasi
   - Tarkibsiz: parollar, kod, foydalanuvchi ma'lumotlari, biznes ma'lumotlar
- Kalit oqib chiqsa — [console.anthropic.com](https://console.anthropic.com/settings/keys) dan revoke qilib yangisi bilan almashtiring.

## Custom system prompt

Sozlamalar → AI bo'limi → "System prompt" maydoni.

Default prompt: SRE assistant rolida, qisqa va texnik javob, O'zbek tilida (Latin).

O'zgartirish mumkin — masalan, kod yozdirish, ma'lum tilda javob berish, korporativ tarzda yozish va h.k.

## Modelni o'zgartirish

Sozlamalar → AI bo'limi → "Model" select.
O'zgartirgandan so'ng Saqlang — keyingi so'rovdan boshlab yangi model.

Tavsiya:
- **Kundalik chat va kichik tahlillar:** Haiku 4.5 (tez, arzon)
- **Batafsil server tahlili, log analizi:** Sonnet 4.6
- **Murakkab muammolar:** Opus 4.7

## Troubleshooting

### "Auth xato: kalit noto'g'ri"
- Kalit nusxalashda probel/boshqa belgi qo'shilmaganmi?
- Kalit tugamaganmi (rotatsiya bo'lishi mumkin)?
- [console](https://console.anthropic.com) da kalit aktivmi?

### "Model topilmadi"
- Model nomini tekshiring (masalan, `claude-haiku-4-5-20251001`)
- Anthropic akkauntingizda shu modelga kirish bormi?
- API tier muammosi bo'lishi mumkin (yangi akkauntlarda free tier cheklovi)

### "API xato: rate limit"
- Bir vaqtning o'zida ko'p so'rov yuborilgan
- Anthropic rate limit'ga yetdingiz — bir oz kutib qayta urining
- Modelni Haiku ga o'zgartiring (limit ko'proq)

### AI tahlili sekin
- Opus eng sekin (10-30s)
- Haiku tez (2-5s)
- Server konteksti katta (>20KB) bo'lsa sekinlashadi
