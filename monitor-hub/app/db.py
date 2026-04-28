"""SQLite via SQLModel."""
import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session, select

DB_URL = "sqlite:////app/data/hub.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


class Server(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    base_url: str                          # http://172.17.0.1:9990
    agent_token: str
    description: Optional[str] = None
    is_active: bool = True

    # Per-server Telegram routing (override defaults)
    # If left blank → fall back to TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env defaults.
    alert_bot_token: Optional[str] = None
    alert_chat_id: Optional[str] = None
    report_bot_token: Optional[str] = None
    report_chat_id: Optional[str] = None

    # Maintenance window — alerts suppressed until this datetime
    maintenance_until: Optional[datetime.datetime] = None

    # Quick health snapshot (updated by scheduler)
    last_check_at: Optional[datetime.datetime] = None
    last_status: Optional[str] = None      # ok | degraded | down | error

    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class Monitor(SQLModel, table=True):
    """Custom monitors that the hub schedules itself (not the agent)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: Optional[int] = Field(default=None, index=True)  # null = global / hub itself
    name: str
    type: str                              # http | tcp | ssl | command
    target: str                            # URL, host:port, hostname, command string
    expected: Optional[str] = None         # status code, regex, exit code
    interval_seconds: int = 300
    is_active: bool = True
    last_run_at: Optional[datetime.datetime] = None
    last_status: Optional[str] = None      # ok | fail
    last_message: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class AlertHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: Optional[int] = Field(default=None, index=True)
    monitor_type: str                      # container | endpoint | database | resource | ssl | custom
    key: str = Field(index=True)           # composite key for dedup, e.g. "container::n8n"
    level: str = "warning"                 # info | warning | critical
    message: str

    # Confirmation: only fire after `consecutive_count` consecutive bad checks
    consecutive_count: int = 1
    fired: bool = False                    # has Telegram been sent yet?

    opened_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, index=True)
    fired_at: Optional[datetime.datetime] = None
    resolved_at: Optional[datetime.datetime] = None
    acked_at: Optional[datetime.datetime] = None

    # Routing audit — which channel actually got the message
    delivered_chat_id: Optional[str] = None
    delivered_via_bot: Optional[str] = None        # bot id (first part of token)


class CheckRun(SQLModel, table=True):
    """Every monitoring tick — for the timeline view."""
    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: int = Field(index=True)
    ran_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, index=True)
    duration_ms: Optional[int] = None
    status: str                            # ok | degraded | down | error
    summary: Optional[str] = None
    payload_json: Optional[str] = None     # raw status JSON (truncated)


class WebhookEvent(SQLModel, table=True):
    """External services can POST events here to be forwarded as alerts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    received_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, index=True)
    source: str                            # arbitrary label e.g. "github", "stripe"
    level: str = "info"
    title: str
    body: Optional[str] = None
    server_id: Optional[int] = None
    forwarded_to: Optional[str] = None


class ScalingRule(SQLModel, table=True):
    """Auto-scale rule for a Swarm service.

    Fires when local-replica avg CPU/mem crosses thresholds. Scales the
    service via `docker service scale`. Cooldown prevents flap.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: int = Field(index=True)              # which server (manager) hosts the service
    service_name: str = Field(index=True)           # docker service name
    metric: str = "cpu"                             # cpu | mem
    scale_up_threshold: float = 70.0                # %
    scale_down_threshold: float = 30.0              # %
    min_replicas: int = 1
    max_replicas: int = 10
    step: int = 1                                   # how many replicas to add/remove per event
    cooldown_seconds: int = 300                     # min seconds between scale ops
    is_active: bool = True

    # Runtime state
    last_scale_at: Optional[datetime.datetime] = None
    last_scale_to: Optional[int] = None             # last replica count we set
    last_metric_value: Optional[float] = None

    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class ScaleEvent(SQLModel, table=True):
    """Audit log for every scale operation (auto or manual)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: int = Field(index=True)
    service_name: str = Field(index=True)
    direction: str                                  # up | down | manual
    from_replicas: int
    to_replicas: int
    reason: Optional[str] = None                    # e.g. "cpu=85% > 70%"
    triggered_by: str = "auto"                      # auto | <admin user>
    ok: bool = True
    error: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, index=True)


class InstallToken(SQLModel, table=True):
    """One-time token for self-register install flow.

    Hub generates → user runs script with token → script registers server back.
    Token expires after 1 hour or on first use.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    suggested_name: Optional[str] = None        # admin pre-fills before generating
    suggested_description: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    expires_at: datetime.datetime
    used_at: Optional[datetime.datetime] = None
    registered_server_id: Optional[int] = None  # set when register succeeds
    created_by: Optional[str] = None            # admin username


class AISettings(SQLModel, table=True):
    """Singleton — id always = 1."""
    id: int = Field(default=1, primary_key=True)
    provider: str = "gemini"   # gemini | groq | openrouter | cerebras | anthropic | openai | deepseek | custom
    api_key: Optional[str] = None
    model: str = "gemini-1.5-flash-latest"
    base_url: Optional[str] = None    # only used for 'custom' provider
    enabled: bool = False
    system_prompt: str = (
        "Sen monitoring tizimining SRE yordamchisisan. "
        "Qisqa, texnik javoblar ber. O'zbek tilida (Latin) javob ber. "
        "Server status JSON berilsa: anomaliyalarni topish (yuqori disk/RAM, "
        "ishlamayotgan containerlar, javobsiz endpointlar, tugayotgan SSL). "
        "Aniq buyruqlar tavsiya qil. Ortiqcha so'z yo'q."
    )


class HubSettings(SQLModel, table=True):
    """Singleton — id always = 1. Admin-managed runtime settings (Telegram, schedule)."""
    id: int = Field(default=1, primary_key=True)

    # ── Telegram defaults (override env when set) ─────────────────────────────
    telegram_bot_token: Optional[str] = None              # if blank → env TELEGRAM_BOT_TOKEN
    default_chat_id: Optional[str] = None                 # if blank → env TELEGRAM_CHAT_ID
    alert_chat_id: Optional[str] = None                   # if blank → falls back to default
    report_chat_id: Optional[str] = None                  # if blank → falls back to default

    # ── Scheduler tuning ──────────────────────────────────────────────────────
    watchdog_interval_seconds: int = 60
    resource_interval_seconds: int = 300
    confirm_ticks: int = 2

    # Daily times (server-local hh:mm) — applied at next restart
    backup_hour: int = 2
    backup_minute: int = 0
    ssl_hour: int = 6
    ssl_minute: int = 0
    digest_hour: int = 8
    digest_minute: int = 0

    # ── Toggles ───────────────────────────────────────────────────────────────
    enable_watchdog: bool = True
    enable_resource: bool = True
    enable_ssl_daily: bool = True
    enable_backup_daily: bool = True
    enable_daily_digest: bool = True

    # AI-generated daily digest (replaces templated when AI is enabled)
    use_ai_digest: bool = False

    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    role: str                              # user | assistant
    content: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, index=True)


def init_db():
    SQLModel.metadata.create_all(engine)
    # SQLite ALTER TABLE for schema additions on existing DBs
    from sqlalchemy import text, inspect as sa_inspect
    insp = sa_inspect(engine)

    migrations = {
        "server": [
            ("alert_bot_token", "VARCHAR"),
            ("alert_chat_id", "VARCHAR"),
            ("report_bot_token", "VARCHAR"),
            ("report_chat_id", "VARCHAR"),
            ("maintenance_until", "DATETIME"),
            ("last_check_at", "DATETIME"),
            ("last_status", "VARCHAR"),
        ],
        "alerthistory": [
            ("consecutive_count", "INTEGER DEFAULT 1"),
            ("fired", "BOOLEAN DEFAULT 0"),
            ("fired_at", "DATETIME"),
            ("delivered_chat_id", "VARCHAR"),
            ("delivered_via_bot", "VARCHAR"),
        ],
        "hubsettings": [
            ("use_ai_digest", "BOOLEAN DEFAULT 0"),
        ],
        "aisettings": [
            ("base_url", "VARCHAR"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in migrations.items():
            try:
                existing = {c["name"] for c in insp.get_columns(table)}
            except Exception:
                continue
            for col, kind in cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {kind}"))
        conn.commit()

    with Session(engine) as s:
        if not s.exec(select(AISettings).where(AISettings.id == 1)).first():
            s.add(AISettings(id=1))
            s.commit()
        if not s.exec(select(HubSettings).where(HubSettings.id == 1)).first():
            s.add(HubSettings(id=1))
            s.commit()


def get_session():
    with Session(engine) as session:
        yield session
