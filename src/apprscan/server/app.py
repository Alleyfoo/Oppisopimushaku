"""FastAPI app factory for the companion service."""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router


def create_app(token: str | None = None) -> FastAPI:
    app = FastAPI(title="apprscan companion", version="0.1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    token = token or os.getenv("APPRSCAN_TOKEN") or secrets.token_urlsafe(24)
    app.state.token = token
    return app


app = create_app()
