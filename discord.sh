#!/bin/zsh
# Seahorse Discord Bot — runs with the dev environment
set -e

VENV="$(pwd)/.venv"
UV_PYTHON="$(uv python find 2>/dev/null | grep -v warning | head -1)"
PYTHON_LIBDIR="$($(uv python find 2>/dev/null | grep -v warning | head -1) -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))' 2>/dev/null | grep -v warning)"

export DYLD_LIBRARY_PATH="$PYTHON_LIBDIR:${DYLD_LIBRARY_PATH:-}"
export PYTHONPATH="$(pwd)/python:$VENV/lib/python3.12/site-packages:${PYTHONPATH:-}"
export PYO3_PYTHON="$UV_PYTHON"

# Load environment variables from .env if it exists
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Environment Configuration
export DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# Database Configuration (Postgres for the 50k data test)
export SEAHORSE_DB_TYPE="postgres"
export SEAHORSE_PG_URI="postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise"

# Mixture of Experts (MoE) Configuration
# Models are loaded from .env (Gemini 2.0 + Claude 3.5)
export SEAHORSE_USE_WASM="true"

echo "⚙️  Building Rust FFI Module (seahorse_ffi)..."
uv run maturin develop -m crates/seahorse-ffi/Cargo.toml --quiet

echo "🤖 Starting Seahorse Discord Bot (Standard High-Quality Mode)..."
uv run python -m seahorse_ai.adapters.discord_adapter
