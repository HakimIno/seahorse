#!/bin/bash
# .claude/hooks/pre_task.sh
# Runs before every Claude Code task

echo "🚀 [Seahorse Agent] Pre-task checks..."

# Check Rust toolchain
if command -v cargo &> /dev/null; then
  echo "  ✅ Rust: $(rustc --version)"
else
  echo "  ❌ Rust not found — install via rustup.rs"
  exit 1
fi

# Check Python
if command -v uv &> /dev/null; then
  echo "  ✅ uv: $(uv --version)"
elif command -v python3 &> /dev/null; then
  echo "  ✅ Python: $(python3 --version) (uv recommended)"
else
  echo "  ❌ Python/uv required"
  exit 1
fi

# Check maturin (PyO3 build tool)
if command -v maturin &> /dev/null; then
  echo "  ✅ maturin: $(maturin --version)"
else
  echo "  ⚠️  maturin not found — run: pip install maturin"
fi

echo "✅ Pre-task checks passed"