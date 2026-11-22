from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

ProviderName = Literal["ollama", "gemini"]


class Settings(BaseSettings):
    """All configuration comes from environment variables / backend/.env. No secrets in code."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LOKI"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./loki.db"

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    session_cookie_name: str = "loki_session"
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False  # set true behind HTTPS

    # LLM
    llm_primary_provider: ProviderName = "ollama"
    llm_primary_model: str = "qwen3:4b-instruct"  # non-reasoning: ~0.2 s to first word on the RTX 5060
    llm_warmup: bool = True  # load the primary model at start-up
    llm_fallback_provider: ProviderName | None = None
    llm_fallback_model: str | None = None
    llm_temperature: float = 0.6
    # Includes reasoning tokens on thinking models, so keep it generous.
    llm_max_output_tokens: int = 4096
    llm_connect_timeout_s: float = 5.0
    llm_idle_timeout_s: float = 60.0  # max wait between streamed chunks
    llm_connect_retries: int = 1
    # auto: if the model reports the "thinking" capability, have Ollama return reasoning separately
    # (it is never shown as the answer). false: ask hybrid models to skip reasoning — only safe for models
    # that can actually disable it; thinking-only models then leak reasoning into the reply.
    ollama_think: Literal["auto", "true", "false"] = "auto"

    ollama_base_url: str = "http://localhost:11435"  # LOKI's own GPU-pinned Ollama (scripts/start-ollama.ps1)
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # Voice (Phase 2). Local by default: faster-whisper on the GPU for STT, Kokoro for TTS.
    voice_enabled: bool = True
    stt_provider: Literal["faster_whisper"] = "faster_whisper"
    stt_model: str = "small"  # tiny | base | small | medium | large-v3 | large-v3-turbo ...
    stt_device: Literal["cuda", "cpu", "auto"] = "cuda"
    stt_compute_type: str = "float16"  # int8 on CPU
    stt_language: str | None = None  # None = auto-detect (accents / multiple languages)
    stt_max_utterance_s: float = 60.0
    tts_provider: Literal["kokoro", "none"] = "kokoro"
    tts_model_dir: str = "models/kokoro"
    tts_voice: str = "bm_george"
    tts_speed: float = 1.0

    # Memory (Phase 3)
    embedding_provider: Literal["ollama"] = "ollama"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dim: int = 1024
    memory_top_k: int = 8
    memory_min_similarity: float = 0.35
    memory_dedupe_similarity: float = 0.92
    memory_extraction: bool = True  # global kill-switch; users also have their own toggle
    auto_migrate: bool = True  # run Alembic migrations on start-up

    # Knowledge base / RAG (Phase 4)
    rag_enabled: bool = True
    upload_dir: str = "data/uploads"
    max_upload_mb: int = 20
    max_files_per_upload: int = 200
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 150
    rag_candidates: int = 30  # hybrid-search candidates passed to the reranker
    rag_top_k: int = 6  # passages given to the model
    rerank_model_dir: str = "models/reranker/mxbai-rerank-xsmall-v1"
    rerank_threshold: float = 0.25  # reranker probability below which a passage is not shown to the model

    # Agent / tools (Phase 5)
    tools_enabled: bool = True
    agent_max_steps: int = 12  # model calls per turn (each may call several tools); research needs ~8-10
    approval_timeout_s: float = 300.0  # unanswered approval requests count as "denied"
    searxng_url: str = "http://127.0.0.1:8888"
    reminder_poll_s: float = 15.0
    # Ollama's default context is 4096 tokens: too small once memories, documents and tool definitions are in the
    # prompt (it silently truncates). 12k fits the RTX 5060 alongside Whisper and the embedding model.
    ollama_num_ctx: int = 12288

    # Context window budget for conversation history (characters, rough proxy for tokens)
    context_char_budget: int = 12000
    max_message_chars: int = 8000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("llm_fallback_provider", "llm_fallback_model", "gemini_api_key", "stt_language", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if v == "" else v


@lru_cache
def get_settings() -> Settings:
    return Settings()
