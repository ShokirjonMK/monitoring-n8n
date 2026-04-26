#!/usr/bin/env bash
# monitor-agent — bir qator o'rnatish skripti.
#
# IKKI usul:
#
# A) Tezkor (Hub'ga avtomat ulanish — TAVSIYA):
#    Hub UI'da "Generate install command" tugmasidan olingan buyruqni ishga tushiring:
#      curl -fsSL http://YOUR_HUB:9991/install/<TOKEN> | bash
#    Skript o'rnatadi va Hub'ga avtomat qayd qiladi.
#
# B) Qo'lda (eski usul — INSTALL_TOKEN bo'lmasa):
#    curl -fsSL https://raw.githubusercontent.com/ShokirjonMK/monitoring-n8n/main/install.sh | bash
#    So'ngida tokenni va URL'ni qo'lda Hub formaga yozasiz.

set -euo pipefail

REPO="${MONITOR_REPO:-https://github.com/ShokirjonMK/monitoring-n8n.git}"
AGENT_DIR="${AGENT_DIR:-/opt/monitor-agent}"
PORT="${MONITOR_AGENT_PORT:-9990}"

# Self-register parameters (when launched via Hub /install/<token>)
HUB_URL="${HUB_URL:-}"
INSTALL_TOKEN="${INSTALL_TOKEN:-}"

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

HOSTNAME_GUESS="$(hostname -s 2>/dev/null || echo new-server)"

if [ ! -f config.yml ]; then
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

# Backuplar
backups: []

backup_retention_days: 30

# SSL nazorat
domains: []

# Threshold qiymatlari
thresholds:
  disk_pct: 80
  mem_pct: 85
  load_1m: 5.0
EOF
    ok "config.yml minimal default bilan yaratildi"
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

AGENT_TOKEN=$(cat .agent-secret)

# ─── 5. Build + start ────────────────────────────────────────────────────────

step "4. Container build va ishga tushirish"

docker compose up -d --build 2>&1 | tail -3
sleep 4

if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    ok "Agent ishlamoqda: http://localhost:${PORT}"
else
    err "Agent javob bermayapti — log: docker logs monitor-agent --tail 30"
    exit 1
fi

# ─── 6. Public IP ────────────────────────────────────────────────────────────

PUBLIC_IP="$(curl -fsSL --max-time 5 -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
ok "Public IP: ${PUBLIC_IP}"

# ─── 7. Self-register with Hub (if INSTALL_TOKEN provided) ───────────────────

if [ -n "$HUB_URL" ] && [ -n "$INSTALL_TOKEN" ]; then
    step "5. Hub'ga avtomat qayd qilish"

    REGISTER_PAYLOAD=$(printf '{"name":"%s","public_ip":"%s","port":%d,"agent_token":"%s"}' \
        "$HOSTNAME_GUESS" "$PUBLIC_IP" "$PORT" "$AGENT_TOKEN")

    REG_RESP=$(curl -fsS -m 30 -X POST \
        "${HUB_URL}/register/${INSTALL_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$REGISTER_PAYLOAD" 2>&1) || {

        # Build URL-encoded prefill link
        ENC_NAME=$(printf '%s' "$HOSTNAME_GUESS" | sed 's/ /%20/g')
        ENC_URL=$(printf 'http://%s:%s' "$PUBLIC_IP" "$PORT" | sed 's|:|%3A|g; s|/|%2F|g')
        ENC_TOKEN="$AGENT_TOKEN"
        FORM_URL="${HUB_URL}/servers/new?name=${ENC_NAME}&url=${ENC_URL}&token=${ENC_TOKEN}"

        err "Hub agent'ga ulana olmadi (server bilan tarmoqda muammo)."
        echo
        echo "  $(c_yellow "Sabab")  Hub (${HUB_URL%:*}) shu serverdagi ${PORT} portga kira olmadi."
        echo "          Eng ehtimoliy: firewall port ${PORT}'ni blok qilmoqda."
        echo
        echo "  $(c_bold "TUZATISH (1 daqiqa):")"
        echo "    1. Yangi serverda firewall ochish:"
        echo "       $(c_blue "sudo ufw allow ${PORT}/tcp")"
        echo "       (yoki) $(c_blue "sudo iptables -A INPUT -p tcp --dport ${PORT} -j ACCEPT")"
        echo "       (yoki) hosting panel firewall'idan ${PORT} ni oching"
        echo
        echo "    2. Hub UI'da bu havolaga kiring (forma avtomat to'ladi):"
        echo "       $(c_green "${FORM_URL}")"
        echo
        echo "    3. Avval $(c_bold "Aloqani sinash") ni bosing → yashil bo'lsa $(c_bold "Saqlash")"
        echo
        echo "  $(c_bold "ALTERNATIVA — qo'lda yozish:")"
        echo "    Nomi:  $HOSTNAME_GUESS"
        echo "    URL:   http://${PUBLIC_IP}:${PORT}"
        echo "    Token: $AGENT_TOKEN"
        echo
        exit 1
    }

    if echo "$REG_RESP" | grep -q '"ok":[ ]*true'; then
        ok "Hub'da qayd qilindi! Hub UI'ni yangilang — server ro'yxatda paydo bo'ladi."
        cat <<EOT


$(c_bold "═════════════════════════════════════════════════════════════")
$(c_green "✓ Tayyor! Hub avtomat qayd qildi.")
$(c_bold "═════════════════════════════════════════════════════════════")

  Server: $(c_bold "$HOSTNAME_GUESS")
  URL:    http://${PUBLIC_IP}:${PORT}
  Hub:    ${HUB_URL}

Keyingi qadam: ${HUB_URL}/servers ga kiring va serverni
to'liq config qiling (endpointlar, bazalar, backuplar).

Config faylni tahrirlang:
  $(c_blue "nano $AGENT_DIR/config.yml")

Qayta yuklash:
  $(c_blue "curl -X POST -H 'Authorization: Bearer \$(cat $AGENT_DIR/.agent-secret)' http://localhost:${PORT}/reload")

EOT
    else
        warn "Register javob: $REG_RESP"
    fi
else
    # Manual mode — print info
    cat <<EOT


$(c_bold "═════════════════════════════════════════════════════════════")
$(c_green "✓ Agent o'rnatildi va ishlamoqda!")
$(c_bold "═════════════════════════════════════════════════════════════")

$(c_bold "Hub UI'ga quyidagilarni kiriting:")

  $(c_bold "Nomi:")        ${HOSTNAME_GUESS}
  $(c_bold "Agent URL:")   http://${PUBLIC_IP}:${PORT}
  $(c_bold "Token:")       ${AGENT_TOKEN}

EOT
fi
