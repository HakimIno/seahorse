# Multi-stage build for Seahorse AI Agent
FROM rust:1.85-slim-bookworm AS chef
RUN cargo install cargo-chef
WORKDIR /app

FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-json recipe.json

FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
# Build dependencies - this is the caching layer
RUN cargo chef cook --release --recipe-json recipe.json
COPY . .
RUN cargo build --release

# Python production stage
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast python package management
RUN pip install uv

# Copy Rust build artifact
COPY --from=builder /app/target/release/libseahorse_ffi.so /app/python/seahorse_ai/libseahorse_ffi.so

# Copy Python codebase
COPY . .

# Install dependencies using uv
RUN uv sync --frozen --no-cache

# Entrypoint for the agent
CMD ["uv", "run", "python", "-m", "seahorse_ai.adapters.discord_adapter"]
