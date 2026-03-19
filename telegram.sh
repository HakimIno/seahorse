#!/bin/zsh
# Seahorse Telegram Bot — runs with the dev environment
# Usage: ./telegram.sh

set -e

VENV="$(pwd)/.venv"
UV_PYTHON="$(uv python find 2>/dev/null | grep -v warning | head -1)"
PYTHON_LIBDIR="$($(uv python find 2>/dev/null | grep -v warning | head -1) -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))' 2>/dev/null | grep -v warning)"

export DYLD_LIBRARY_PATH="$PYTHON_LIBDIR:${DYLD_LIBRARY_PATH:-}"
PV=$($UV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
export PYTHONPATH="$(pwd)/python:$VENV/lib/python$PV/site-packages:${PYTHONPATH:-}"
export PYO3_PYTHON="$UV_PYTHON"

# Load environment variables from .env if it exists
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    # Export explicitly, stripping potential surrounding quotes
    key=$(echo "$line" | cut -d'=' -f1)
    value=$(echo "$line" | cut -d'=' -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    export "$key"="$value"
  done < .env
fi

# Environment Configuration
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
export TELEGRAM_ALERTS_CHAT_ID="${TELEGRAM_ALERTS_CHAT_ID:-}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# Database Configuration (Postgres for production-grade testing)
export SEAHORSE_DB_TYPE="${SEAHORSE_DB_TYPE:-postgres}"
export SEAHORSE_PG_URI="${SEAHORSE_PG_URI:-postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise}"
export SEAHORSE_USE_WASM="true"

echo "⚙️  Building Rust Router & FFI..."
uv run maturin develop -m crates/seahorse-ffi/Cargo.toml --quiet

# Start Rust Router in the background if not already running
if ! lsof -iTCP:8000 -sTCP:LISTEN > /dev/null; then
  echo "🚀 Starting Rust Router (Background)..."
  # Use nohup or just & to keep it alive
  cargo run --release -p seahorse-router > /tmp/seahorse_router.log 2>&1 &
  
  # Wait for port 8000 to be active
  echo "⏳ Waiting for Router to be ready on port 8000..."
  for i in {1..30}; do
    if lsof -i:8000 > /dev/null; then
      echo "✅ Router is READY."
      break
    fi
    sleep 2
  done
fi

echo "📱 Starting Seahorse Telegram Bot..."
uv run python -m seahorse_ai.adapters.telegram_adapter
