#!/usr/bin/env bash
# monitor-agent — bir qator o'rnatish skripti.
#
# Foydalanish (yangi serverda):
#   curl -fsSL https://raw.githubusercontent.com/ShokirjonMK/monitoring-n8n/main/install.sh | bash
#
# Yoki repoga tegmasdan, mahalliy nusxa bilan:
#   bash install.sh
#
# Skript:
#   1. /opt/monitor-agent papkasini yaratadi (yoki yangilaydi)
#   2. config.yml ni minimal default bilan yaratadi (allaqachon mavjud bo'lmasa)
#   3. .agent-secret tokenini generatsiya qiladi
#   4. Container ishga tushuradi
#   5. So'ngida Hub'ga qo'shish uchun BARCHA ma'lumotlarni chop etadi

set -euo pipefail

REPO="https://github.com/ShokirjonMK/monitoring-n8n.git"
AGENT_DIR="/opt/monitor-agent"
PORT="${MONITOR_AGENT_PORT:-9990}"

c_red()    { printf "\033[31m%s\033[0m" "$*"; }
c_green()  { printf "\033[32m%s\033[0m" "$*"; }
c_yellow() { printf "\033[33m%s\033[0m" "$*"; }
c_blue()   { printf "\033[34m%s\033[0m" "$*"; }
c_bold()   { printf "\033[1m%s\033[0m" "$*"; }

step() { printf "\n%s %s\n" "$(c_blue "▶")" "$(c_bold "$*")"; }
ok()   { printf "  %s %s\n" "$(c_green "✓")" "$*"; }
warn() { printf "  %s %s\n" "$(c_yellow "⚠")" "$*"; }
err()  { printf "  %s %s\n" "$(c_red "✗")" "$*"; }

# ─── 1. Pre-flight ───────────────────────────────────────────────────────────

step "1. Sistema talablari tekshiruvi"

if ! command -v docker >/dev/null 2>&1; then
    err "Docker topilmadi. Avval Docker o'rnating: https://docs.docker.com/engine/install/"
    exit 1
fi
ok "Docker: $(docker --version)"

if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 topilmadi (docker compose). Yangilang."
    exit 1
fi
ok "Docker Compose: $(docker compose version --short)"

if [ "$(id -u)" -ne 0 ] && ! groups | grep -q docker; then
    warn "Siz root emassiz va docker guruhida emas — sudo yoki docker guruhiga qo'shilish kerak bo'lishi mumkin."
fi

# ─── 2. Repository ───────────────────────────────────────────────────────────

step "2. Kod"

if [ -d "$AGENT_DIR/.git" ]; then
    cd "$AGENT_DIR" && git pull --ff-only 2>&1 | tail -3
    ok "Mavjud klon yangilandi: $AGENT_DIR"
elif [ -d "$AGENT_DIR" ] && [ -f "$AGENT_DIR/Dockerfile" ]; then
    ok "Mavjud o'rnatish topildi: $AGENT_DIR (klon emas)"
else
    if [ -d "$AGENT_DIR" ]; then
        warn "$AGENT_DIR mavjud lekin agent emas — yangi joyga klonlanadi"
        AGENT_DIR="/opt/monitor-agent-$(date +%s)"
    fi
    TMP="/tmp/mon-$$"
    git clone --depth 1 "$REPO" "$TMP" 2>&1 | tail -2
    mkdir -p "$AGENT_DIR"
    cp -r "$TMP/monitor-agent/." "$AGENT_DIR/"
    rm -rf "$TMP"
    ok "Klonlandi: $AGENT_DIR"
fi

cd "$AGENT_DIR"

# ─── 3. Config ───────────────────────────────────────────────────────────────

step "3. Konfiguratsiya"

if [ ! -f config.yml ]; then
    HOSTNAME_GUESS="$(hostname -s 2>/dev/null || echo new-server)"
    cat > config.yml <<EOF
# monitor-agent konfiguratsiyasi.
# Tahrirlang — kuzatiladigan endpointlar, bazalar va backuplarni qo'shing.

server_name: ${HOSTNAME_GUESS}

# HTTP healthcheck'lar
endpoints: []
# Misol:
#   - {name: "Mening saytim", url: "http://172.17.0.1:80/", expect: 200}

# Postgres (docker exec) yoki SQLite (file)
databases: []
# Misol:
#   - {name: app, type: postgres, container: app-postgres, db: app, user: app}
#   - {name: cache, type: sqlite, path: /opt/myapp/cache.db}

# Backuplar
backups: []
# Misol:
#   - {name: app, type: pg_dump, container: app-postgres, db: app, user: app}
#   - {name: cache, type: sqlite_copy, path: /opt/myapp/cache.db}

backup_retention_days: 30

# SSL nazorat
domains: []
# Misol:
#   - {host: example.com, port: 443}

# Threshold qiymatlari
thresholds:
  disk_pct: 80
  mem_pct: 85
  load_1m: 5.0
EOF
    ok "config.yml minimal default bilan yaratildi"
    warn "Kuzatish uchun config.yml ni tahrirlab endpointlar/bazalarni qo'shing!"
else
    ok "Mavjud config.yml saqlandi"
fi

# ─── 4. Token ────────────────────────────────────────────────────────────────

if [ ! -f .agent-secret ]; then
    openssl rand -hex 32 > .agent-secret
    chmod 600 .agent-secret
    ok "Yangi token generatsiya qilindi"
else
    ok "Mavjud token saqlandi"
fi

TOKEN=$(cat .agent-secret)

# ─── 5. Build + start ────────────────────────────────────────────────────────

step "4. Container build va ishga tushirish"

docker compose up -d --build 2>&1 | tail -3
sleep 3

if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    ok "Agent ishlamoqda: http://localhost:${PORT}"
else
    warn "Agent javob bermayapti — log ko'rib chiqing: docker logs monitor-agent --tail 30"
fi

# ─── 6. Print Hub-add instructions ───────────────────────────────────────────

PUBLIC_IP="$(curl -fsSL --max-time 5 -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"

cat <<EOT


$(c_bold "═════════════════════════════════════════════════════════════")
$(c_green "✓ Agent o'rnatildi va ishlamoqda!")
$(c_bold "═════════════════════════════════════════════════════════════")

$(c_bold "Endi Hub UI'da quyidagi ma'lumotlarni kiriting:")

  $(c_bold "Nomi:")        ${HOSTNAME_GUESS:-$(hostname -s)}
  $(c_bold "Agent URL:")   http://${PUBLIC_IP}:${PORT}
  $(c_bold "Token:")       ${TOKEN}

$(c_bold "Hub URL:")    http://YOUR_HUB:9991/servers/new

─────────────────────────────────────────────────────────────

$(c_bold "Keyingi qadamlar:")

1. config.yml ni tahrirlang:
   $(c_blue "nano $AGENT_DIR/config.yml")
   — endpointlar, bazalar, backuplar va SSL domenlarini qo'shing

2. Configni qayta yuklang (restartsiz):
   $(c_blue "curl -X POST -H 'Authorization: Bearer \$(cat $AGENT_DIR/.agent-secret)' http://localhost:${PORT}/reload")

3. Agent loglari:
   $(c_blue "docker logs monitor-agent --tail 50 -f")

4. Hub UI'da serverni qo'shing — Hub avtomat tarzda nazorat boshlaydi.

EOT
