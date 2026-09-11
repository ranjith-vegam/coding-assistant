"""FastAPI app entrypoint.

Mirrors the shape of the other services in this platform (agent_studio,
model-orchestrator, ...): a `create_app()` factory, a `main()` that runs it
under uvicorn, and `python -m samixa_code` / `uv run start` both landing
here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from samixa_code.api.chat import router as chat_router
from samixa_code.api.health import router as health_router
from samixa_code.settings import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="samixa-code-backend", version="0.1.0")
    app.include_router(health_router)
    app.include_router(chat_router)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "samixa_code.main:app",
        host=settings.service_host,
        port=settings.service_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
