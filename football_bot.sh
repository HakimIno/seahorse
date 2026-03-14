#!/bin/zsh
# Seahorse Football Bot — dedicated instance
# Usage: ./football_bot.sh

set -e

VENV="$(pwd)/.venv"
UV_PYTHON="$(uv python find 2>/dev/null | grep -v warning | head -1)"
PYTHON_LIBDIR="$($(uv python find 2>/dev/null | grep -v warning | head -1) -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))' 2>/dev/null | grep -v warning)"

export DYLD_LIBRARY_PATH="$PYTHON_LIBDIR:${DYLD_LIBRARY_PATH:-}"
export PYTHONPATH="$(pwd)/python:$VENV/lib/python3.12/site-packages:${PYTHONPATH:-}"
export PYO3_PYTHON="$UV_PYTHON"

# Load environment variables from .env
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    key=$(echo "$line" | cut -d'=' -f1)
    value=$(echo "$line" | cut -d'=' -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    export "$key"="$value"
  done < .env
fi

# Override for Football Bot
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN_FOOTBALL:-$TELEGRAM_BOT_TOKEN}"
export TELEGRAM_ALERTS_CHAT_ID="${TELEGRAM_ALERTS_FOOTBALL_CHAT_ID:-$TELEGRAM_ALERTS_CHAT_ID}"
export SEAHORSE_TELEGRAM_WELCOME="⚽ สวัสดีครับ! ผม Football Analyst AI พร้อมช่วยคุณวิเคราะห์แมตช์และราคาน้ำแล้วครับ"
export SEAHORSE_TELEGRAM_NUDGE="[SYSTEM: You are the Football Analyst Bot. Your primary goal is to use the FootballTeam tools to provide high-quality match predictions, xG analysis, and bankroll management advice using the Kelly Criterion. Always try to find an 'edge' against the market.]"

echo "⚙️  Verifying Rust Build..."
uv run maturin develop -m crates/seahorse-ffi/Cargo.toml --quiet

echo "🚀 Starting Football Analyst Bot..."
uv run python -m seahorse_ai.adapters.telegram_adapter
