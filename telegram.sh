#!/bin/zsh
# Seahorse Telegram Bot — runs with the dev environment
# Usage: ./telegram.sh

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
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
export TELEGRAM_ALERTS_CHAT_ID="${TELEGRAM_ALERTS_CHAT_ID:-}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# Database Configuration (Postgres for production-grade testing)
export SEAHORSE_DB_TYPE="${SEAHORSE_DB_TYPE:-postgres}"
export SEAHORSE_PG_URI="${SEAHORSE_PG_URI:-postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise}"

echo "📱 Starting Seahorse Telegram Bot..."
uv run python -m seahorse_ai.adapters.telegram_adapter
