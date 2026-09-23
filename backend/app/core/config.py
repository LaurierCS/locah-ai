"""Central configuration. Every value comes from the environment; nothing is hardcoded."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

# Repo-root `.env` is the documented location; backend/.env can override it.
_ENV_FILES = (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    # Model ID is TBD until S1. Schema is vector(1024); a new model/dim needs a migration.
    embedding_model: str = ""
    embedding_dimensions: int = 1024

    database_url: str = "postgresql+psycopg://locah:locah@localhost:5432/locah"

    # INV-1: explicit public hostnames, not a bare *.wlu.ca wildcard.
    crawl_allowlist: str = "wlu.ca,www.wlu.ca,students.wlu.ca,legacy.wlu.ca"
    crawl_user_agent: str = "LOCAH.ai (Laurier Computing Society; development@lauriercs.org)"
    crawl_delay_seconds: float = 1.0
    crawl_max_pages: int = 5000
    crawl_depth_cap: int = 2
    crawl_content_types: str = "text/html,application/pdf"

    retrieval_top_k: int = 8
    confidence_threshold: float = 0.35

    # INV-6: no aggregate category is reported below this many students.
    k_anonymity_min: int = 5

    admin_token: str = ""
    monthly_cost_cap_cad: float = 60.0

    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.crawl_allowlist.split(",") if h.strip()}

    @property
    def crawl_content_types_list(self) -> list[str]:
        return [ct.strip() for ct in self.crawl_content_types.split(",") if ct.strip()]


settings = Settings()
