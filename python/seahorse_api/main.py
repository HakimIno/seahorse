"""seahorse_api — FastAPI application for the Seahorse Agent."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from seahorse_api.routers import agent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup / shutdown hooks."""
    # Startup
    yield
    # Shutdown (add cleanup here)


app = FastAPI(
    title="Seahorse Agent API",
    description="High-Performance AI Agent — Rust Core + Python Intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(agent.router, prefix="/v1/agent", tags=["agent"])
