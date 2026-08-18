"""
Central, env-driven configuration.

Every value a fork needs to change to make this "theirs" lives here,
loaded from environment variables (see .env.example for the full list
with explanations). Nothing about a specific person is hardcoded in
code — that's what makes this repo forkable as a template.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- LLM provider (OpenAI-compatible) -----------------------------
    # Defaults target NVIDIA NIM's hosted API catalog (build.nvidia.com).
    # Point these at a self-hosted NIM container, Groq, Together.ai, or
    # any other OpenAI-compatible endpoint without touching any code.
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_api_key: str = ""
    llm_model: str = "meta/llama-3.1-8b-instruct"
    llm_max_output_tokens: int = 400
    llm_timeout_seconds: float = 20.0
    llm_temperature: float = 0.3

    # --- Persona / branding --------------------------------------------
    # What the assistant calls itself and the person it represents.
    # Edit these (or the env vars) to re-personalize a fork in one place.
    assistant_name: str = "Portfolio Assistant"
    owner_name: str = "the site owner"
    owner_pronouns: str = "they/them"
    tone_description: str = "friendly, professional, and concise"
    contact_redirect_message: str = (
        "For anything like contact details or scheduling, please use the "
        "contact form / links elsewhere on this site rather than asking me directly."
    )

    # --- CORS ------------------------------------------------------------
    # Comma-separated list of origins allowed to call this API, e.g.
    # "https://yourportfolio.com,https://www.yourportfolio.com"
    allowed_origins: str = "http://localhost:3000"

    # --- Guardrails --------------------------------------------------------
    max_turns_per_session: int = 20
    max_input_chars: int = 2000
    rate_limit_per_minute: int = 20
    session_ttl_seconds: int = 3600

    # --- Session storage ---------------------------------------------------
    # "memory" (default, correct for a single-instance VPS deployment) or
    # "redis" (for forks that scale to multiple backend instances).
    session_backend: str = "memory"
    redis_url: str = ""

    # --- Documents ----------------------------------------------------------
    documents_dir: str = "documents"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
