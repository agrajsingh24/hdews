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
    for raw in path.read_text().splitlines():
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


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"  # development | test | production
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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def demo_endpoints_active(self) -> bool:
        # Demo/scenario endpoints can never be active in production configuration.
        return self.enable_demo_endpoints and not self.is_production


def load_settings(**overrides) -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    env = os.environ
    values = dict(
        app_env=env.get("HDEWS_ENV", "development"),
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
    )
    values.update(overrides)
    url = values["database_url"]
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        path = Path(url[len("sqlite:///"):])
        if not path.is_absolute():  # relative paths are resolved against the repository root
            values["database_url"] = f"sqlite:///{REPO_ROOT / path}"
    return Settings(**values)
