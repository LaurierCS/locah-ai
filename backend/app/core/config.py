"""Central configuration. Every value comes from the environment; nothing is hardcoded."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    embedding_model: str = ""

    database_url: str = "postgresql+psycopg://locah:locah@localhost:5432/locah"

    # Crawler scope. INV-1: the knowledge base holds public wlu.ca pages only.
    crawl_allowlist: str = "wlu.ca,www.wlu.ca,students.wlu.ca"
    crawl_user_agent: str = "LOCAH.ai (Laurier Computing Society)"
    crawl_delay_seconds: float = 1.0
    crawl_max_pages: int = 5000

    retrieval_top_k: int = 8
    confidence_threshold: float = 0.35

    # INV-6: no aggregate category is reported below this many students.
    k_anonymity_min: int = 5

    admin_token: str = ""
    monthly_cost_cap_cad: float = 60.0

    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.crawl_allowlist.split(",") if h.strip()}


settings = Settings()
