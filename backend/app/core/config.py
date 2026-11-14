import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("biopulse.config")


def _load_dotenv_file() -> None:
    """Load key=value pairs from backend/.env if present without external dependency."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and (key not in os.environ or val):
                os.environ[key] = val
    except OSError as exc:
        logger.warning("Could not read .env file: %s", exc)


_load_dotenv_file()


def get_secret_key() -> str:
    """Resolve secret key safely: Environment -> Local File -> Ephemeral Random Generation."""
    env_secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    secret_file = Path(__file__).resolve().parents[2] / "jwt_secret.txt"
    if secret_file.exists():
        content = secret_file.read_text(encoding="utf-8").strip()
        if content:
            return content
    logger.warning(
        "Generating ephemeral secret. Instance-isolated! Set JWT_SECRET_KEY in production."
    )
    return secrets.token_hex(32)


class Settings:
    """Centralized configuration loaded from environment variables."""

    def __init__(self) -> None:
        self.app_host: str = os.getenv("APP_HOST", "127.0.0.1")
        self.app_port: int = int(os.getenv("APP_PORT", "8080"))
        self.app_env: str = os.getenv("APP_ENV", "development")

        raw_origins = os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:8080,http://localhost:8080",
        )
        self.cors_allowed_origins: list[str] = [
            o.strip() for o in raw_origins.split(",") if o.strip()
        ]

        self.jwt_secret_key: str = get_secret_key()
        self.admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "").strip()

        # Database settings (PostgreSQL primary; SQLite local fallback for instant testing)
        # TODO(security): Enforce PostgreSQL mTLS client certificates in VPS production deployment.
        self.database_url: str = os.getenv("DATABASE_URL", "").strip()
        default_sqlite = str(Path(__file__).resolve().parents[2] / "biopulse.db")
        self.sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", default_sqlite)

        # MQTT settings
        self.mqtt_enabled: bool = os.getenv("MQTT_ENABLED", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.mqtt_broker_host: str = os.getenv("MQTT_BROKER_HOST", "broker.emqx.io")
        self.mqtt_broker_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
        self.mqtt_username: str = os.getenv("MQTT_USERNAME", "").strip()
        self.mqtt_password: str = os.getenv("MQTT_PASSWORD", "").strip()
        self.mqtt_client_id_prefix: str = os.getenv(
            "MQTT_CLIENT_ID_PREFIX", "biopulse-backend"
        )
        self.mqtt_topic_prefix: str = os.getenv("MQTT_TOPIC_PREFIX", "biopulse").strip(
            "/"
        )
        self.default_device_id: str = os.getenv("DEFAULT_DEVICE_ID", "bp-device-001")

        # Configurable intervals & thresholds (Section 4.2 of Guide)
        self.telemetry_interval_sec: int = int(
            os.getenv("TELEMETRY_INTERVAL_SEC", "5")
        )
        self.heartbeat_interval_sec: int = int(
            os.getenv("HEARTBEAT_INTERVAL_SEC", "10")
        )
        self.heartbeat_timeout_sec: int = int(
            os.getenv("HEARTBEAT_TIMEOUT_SEC", "30")
        )
        self.fall_impact_threshold_ms2: float = float(
            os.getenv("FALL_IMPACT_THRESHOLD_MS2", "22.0")
        )

        # Telegram Bot settings
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.telegram_bot_handle: str = os.getenv(
            "TELEGRAM_BOT_HANDLE", "@BioPulseCare_bot"
        )
        self.telegram_cooldown_sec: int = int(
            os.getenv("TELEGRAM_COOLDOWN_SEC", "60")
        )


settings = Settings()
