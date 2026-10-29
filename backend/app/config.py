"""Application configuration, loaded from environment variables.

No secrets are hardcoded. See `.env.example` at the repository root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency). Existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# development: local work. test: automated tests. demo: a hosted, internet-facing demonstration (simulator
# on, strict secrets, nothing secret printed). production: simulator off, demo seed refused.
VALID_ENVS = ("development", "test", "demo", "production")
# How the client IP used for rate limiting is determined (HDEWS-041). "peer" = the TCP peer (correct when
# clients connect directly). Behind a platform proxy every request has the proxy's address, so one bucket
# would be shared by all users; choose the X-Forwarded-For entry that your proxy guarantees.
CLIENT_IP_SOURCES = ("peer", "x-forwarded-for-first", "x-forwarded-for-last")


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"  # one of VALID_ENVS
    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'hdews.db'}"
    session_ttl_hours: int = 12
    enable_demo_endpoints: bool = True
    enable_background_reassessment: bool = True
    reassessment_interval_s: int = 300
    llm_provider: str = "none"  # none | anthropic
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_s: int = 20
    frontend_dist: Path = field(default=REPO_ROOT / "frontend" / "dist")
    cors_origins: tuple[str, ...] = ()
    client_ip_source: str = "peer"

    def __post_init__(self) -> None:
        # An unrecognised value (e.g. a typo such as "prod") used to behave like development, with demo
        # endpoints on and no secret checks (HDEWS-040). Fail at start-up instead.
        if self.app_env not in VALID_ENVS:
            raise ValueError(f"HDEWS_ENV must be one of {', '.join(VALID_ENVS)} (got {self.app_env!r}).")
        if self.client_ip_source not in CLIENT_IP_SOURCES:
            raise ValueError(f"CLIENT_IP_SOURCE must be one of {', '.join(CLIENT_IP_SOURCES)} (got {self.client_ip_source!r}).")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_hosted(self) -> bool:
        """Internet-facing configurations: documented default passwords are refused, secrets never printed."""
        return self.app_env in ("demo", "production")

    @property
    def demo_endpoints_active(self) -> bool:
        # Demo/scenario endpoints can never be active in production configuration.
        return self.enable_demo_endpoints and not self.is_production


def load_settings(**overrides) -> Settings:
    # HDEWS_DOTENV=0 disables reading the repository's .env (the test suite sets it so a developer's local
    # .env can never change test behaviour). Real environment variables always win over .env values.
    if os.environ.get("HDEWS_DOTENV", "1") != "0":
        _load_dotenv(REPO_ROOT / ".env")
    env = os.environ
    values = dict(
        app_env=env.get("HDEWS_ENV", "development").strip().lower(),
        database_url=env.get("DATABASE_URL", Settings.database_url),
        session_ttl_hours=int(env.get("SESSION_TTL_HOURS", "12")),
        enable_demo_endpoints=_bool("ENABLE_DEMO_ENDPOINTS", True),
        enable_background_reassessment=_bool("ENABLE_BACKGROUND_REASSESSMENT", True),
        reassessment_interval_s=int(env.get("REASSESSMENT_INTERVAL_S", "300")),
        llm_provider=env.get("LLM_PROVIDER", "none").lower(),
        llm_api_key=env.get("LLM_API_KEY", ""),
        llm_model=env.get("LLM_MODEL", ""),
        llm_timeout_s=int(env.get("LLM_TIMEOUT_S", "20")),
        cors_origins=tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()),
        client_ip_source=env.get("CLIENT_IP_SOURCE", "peer").strip().lower(),
    )
    values.update(overrides)
    url = values["database_url"]
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        path = Path(url[len("sqlite:///"):])
        if not path.is_absolute():  # relative paths are resolved against the repository root
            values["database_url"] = f"sqlite:///{REPO_ROOT / path}"
    return Settings(**values)
