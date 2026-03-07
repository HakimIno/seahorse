#!/bin/zsh
# Seahorse Discord Bot — runs with the dev environment
set -e

VENV="$(pwd)/.venv"
UV_PYTHON="$(uv python find 2>/dev/null | grep -v warning | head -1)"
PYTHON_LIBDIR="$($(uv python find 2>/dev/null | grep -v warning | head -1) -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))' 2>/dev/null | grep -v warning)"

export DYLD_LIBRARY_PATH="$PYTHON_LIBDIR:${DYLD_LIBRARY_PATH:-}"
export PYTHONPATH="$(pwd)/python:$VENV/lib/python3.12/site-packages:${PYTHONPATH:-}"
export PYO3_PYTHON="$UV_PYTHON"

# Environment from dev.sh
export DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
export SEAHORSE_LLM_MODEL="openrouter/google/gemini-3-flash-preview"

echo "🤖 Starting Seahorse Discord Bot..."
uv run python -m seahorse_ai.adapters.discord_adapter
