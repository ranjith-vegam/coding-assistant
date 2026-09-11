"""Env-driven configuration for the coding-assistant backend.

Follows the convention used across the rest of the AI platform: plain
SCREAMING_SNAKE_CASE env vars, loaded once at import time via pydantic-settings,
with a `.env` file for local dev. Nothing here is a secret worth encrypting --
the model-orchestrator API key is a shared dev token today (see .env.example).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Model orchestrator (external -- we do not host models ourselves) ---
    model_orch_base_url: str = "http://192.168.0.99:9900"
    model_orch_api_key: str = "model-orch-dev-token"
    model_orch_chat_model: str = "Qwen3.8-27B"
    model_orch_embed_model: str = "bge-m3"
    # The orchestrator's /v1/chat/completions hangs indefinitely on stream=true
    # today (confirmed by hand: 90s+, zero bytes). Keep this False until that's
    # fixed upstream -- see docs/ARCHITECTURE.md "Known orchestrator gaps".
    model_orch_streaming_enabled: bool = False
    model_orch_timeout_seconds: float = 180.0
    # Confirmed live: the deployed chat model's context window is 16384
    # tokens TOTAL (input + output) -- a single read_file call once put ~12k
    # input tokens on the wire by itself and got a 400 back. The agent loop
    # trims history to fit (model_orch_context_window_tokens - reply budget)
    # before every call -- see llm/token_budget.py. Raise this only once
    # you've confirmed the deployed model's actual window is larger.
    model_orch_context_window_tokens: int = 16384
    # Kept modest on purpose: most turns (a tool call, or a short answer)
    # don't need much, and every token reserved here is a token NOT available
    # for input against the 16k ceiling above.
    model_orch_reply_max_tokens: int = 1024
    # A "possibly_truncated" parse (toolcall_parser.py) usually means a
    # response hit model_orch_reply_max_tokens mid tool-call -- the fix that
    # addresses the cause is retrying with MORE reply room, not resending the
    # same request. See agent/loop.py's _chat_with_truncation_retry.
    truncation_retry_max_attempts: int = 3
    # Multiplicative growth per retry attempt (mirrors CONTEXT_RETRY_SHRINK_FACTOR's
    # shape, opposite direction). The grown value is still capped at half the
    # context window in loop.py, so a runaway retry can't itself trigger a
    # context-length error.
    truncation_retry_growth_factor: float = 1.6

    # --- This service's own listening socket ---
    # 0.0.0.0: reachable from other machines (e.g. VS Code on a laptop talking
    # to a backend hosted on a dev box), not just loopback. If you only ever
    # run the extension and this backend on the same machine, override to
    # 127.0.0.1 in .env to avoid exposing it on the LAN.
    service_host: str = "0.0.0.0"
    service_port: int = 8765

    # --- Logging ---
    log_level: str = "INFO"

    # --- Workspace retrieval index ---
    # Where per-workspace index state (sqlite/lancedb files) is cached. Keyed
    # by a hash of the workspace root path, so multiple workspaces don't collide.
    # NOTE: not wired up to anything yet -- the retrieval/indexing layer this
    # was meant for hasn't been built. Placeholder, not live config.
    index_cache_dir: str = "~/.cache/samixa/index"

    # --- Chat persistence (Redis) ---
    # Points at the redis-stack instance already running for this project
    # (container redis-stack-harshit, host port 6336 -> container 6379).
    # Plain string keys + JSON (see chat_store.py) -- no RedisJSON/RediSearch
    # module dependency, works against any Redis server.
    redis_url: str = "redis://localhost:6336/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
