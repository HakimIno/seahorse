#!/bin/bash
# .claude/hooks/pre_commit.sh
# Runs before git commit

echo "🔐 [Seahorse Agent] Pre-commit gate..."

FAIL=0

# 1. Rust tests
echo "  → cargo test --workspace..."
cargo test --workspace --quiet 2>&1 | tail -3
[ ${PIPESTATUS[0]} -ne 0 ] && FAIL=1

# 2. Rust fmt
cargo fmt --all -- --check 2>&1
[ $? -ne 0 ] && echo "  ❌ rustfmt failed — run: cargo fmt --all" && FAIL=1

# 3. Clippy
cargo clippy --workspace -- -D warnings 2>&1 | tail -5
[ ${PIPESTATUS[0]} -ne 0 ] && FAIL=1

# 4. Python tests
echo "  → pytest python/..."
uv run pytest python/ -q 2>&1 | tail -5
[ ${PIPESTATUS[0]} -ne 0 ] && FAIL=1

# 5. Python typing
echo "  → mypy python/..."
uv run mypy python/ --strict --quiet 2>&1 | tail -5
[ ${PIPESTATUS[0]} -ne 0 ] && FAIL=1

if [ $FAIL -ne 0 ]; then
  echo "❌ Pre-commit failed — fix errors above"
  exit 1
fi

echo "✅ All checks passed — committing"