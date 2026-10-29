from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # LLM gateway (OpenAI-compatible). Keys stay server-side.
    llm_base_url: str = ""
    llm_api_key: str = ""
    chat_model: str = ""
    extract_model: str = ""
    embed_model: str = ""
    llm_timeout_s: float = 30.0

    # One shared budget across JSON attempts, including repair. No capability probes.
    llm_json_budget_s: float = 8.0
    llm_send_temperature: bool = False
    llm_json_mode: bool = True
    # Operator-provided estimates in USD per million tokens; no unknown-model fallback.
    price_table: dict[str, tuple[float, float]] = {}
    price_basis: str = "operator configured estimates; not billing data"

    # Scraper politeness
    scraper_user_agent: str = "CareerPathHackathonBot/0.1 (+contact: team@example.com)"
    scraper_min_delay_s: float = 2.0

    # Ranking weights (hybrid = skill overlap + embedding cosine, optional LLM re-rank)
    w_skill_overlap: float = 0.6
    w_embedding: float = 0.4
    w_seniority: float = 0.1  # weights are renormalised over the signals that are available
    skill_jaccard_blend: float = 0.2  # skill_score = (1 - blend) * coverage + blend * jaccard
    embed_batch_size: int = 64
    llm_rerank: bool = False
    llm_rerank_top_k: int = 20

    max_questions: int = 6
    max_upload_mb: int = 5
    cors_origins: list[str] = ["http://localhost:5173"]

    data_dir: Path = BACKEND_DIR / "data"


settings = Settings()
