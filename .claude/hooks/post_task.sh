#!/bin/bash
# .claude/hooks/post_task.sh
# Runs after every Claude Code task

echo "🔍 [Seahorse Agent] Post-task validation..."

# Rust: clippy + fmt check
if [ -f "Cargo.toml" ]; then
  echo "  → Running cargo clippy..."
  cargo clippy --workspace --all-features -- -D warnings 2>&1 | tail -5
  echo "  → Checking rustfmt..."
  cargo fmt --all -- --check 2>&1 | tail -5
fi

# Python: ruff lint check
if [ -f "pyproject.toml" ]; then
  echo "  → Running ruff check via uv..."
  uv run ruff check python/ 2>&1 | tail -5
fi

echo "✅ Post-task validation done"