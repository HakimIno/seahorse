---
name: release
description: Seahorse release process — version bumping, maturin wheel build, changelog, git tagging
---

# Seahorse — Release Skill

## Release Types

| Type  | When                              | Example         |
| ----- | --------------------------------- | --------------- |
| patch | bug fixes, no API change          | `0.1.0 → 0.1.1` |
| minor | new features, backward compatible | `0.1.0 → 0.2.0` |
| major | breaking API changes              | `0.1.0 → 1.0.0` |

---

## Version Bump (all files must be in sync)

Files to update:

1. `Cargo.toml` (workspace) — `version = "X.Y.Z"`
2. `pyproject.toml` — `version = "X.Y.Z"`
3. `.claude/settings.json` — `"version": "X.Y.Z"`
4. `CHANGELOG.md` — add new section

```bash
# Bump version consistently
NEW_VERSION="0.2.0"
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" Cargo.toml pyproject.toml

# Verify all crates in workspace have matching versions
cargo metadata --no-deps | jq '.packages[].version' | sort -u
```

---

## Pre-Release Gate

Run the full pre-commit suite first:

```bash
# Must all pass before tagging
cargo fmt --all -- --check
cargo clippy --workspace --all-features -- -D warnings
cargo nextest run --workspace
uv run ruff check python/
uv run mypy python/ --strict
uv run pytest python/ -q
```

---

## Build Python Wheel (maturin)

```bash
# Development / editable install
uv run maturin develop --features pyo3/extension-module

# Release wheel (current platform)
uv run maturin build --release

# Cross-platform wheels (for PyPI)
uv run maturin build --release --target x86_64-unknown-linux-gnu
uv run maturin build --release --target aarch64-unknown-linux-gnu
uv run maturin build --release --target x86_64-apple-darwin
uv run maturin build --release --target aarch64-apple-darwin

# Output: target/wheels/seahorse_ffi-X.Y.Z-cpXXX-*.whl
```

---

## Build Rust Binaries

```bash
# Release binary with mold linker
RUSTFLAGS="-C link-arg=-fuse-ld=mold" cargo build --release --workspace

# Verify binary size
ls -lh target/release/seahorse-router

# Strip debug symbols for distribution
strip target/release/seahorse-router
```

---

## CHANGELOG Format

```markdown
# Changelog

## [0.2.0] - 2025-XX-XX

### Added

- HNSW memory backend now supports dynamic ef tuning per query
- New `WebSearchTool` in `seahorse_ai/tools/web.py`

### Changed

- `AgentMemory::search` signature: `ef` param now required (was default 50)
- LiteLLM upgraded to 1.36 — streaming API change

### Fixed

- GIL deadlock when Python calls FFI from multiple threads simultaneously
- HNSW index not persisted across process restarts

### Performance

- FFI call overhead reduced from 120µs to 40µs (bytemuck zero-copy)
- HNSW M=16 ef_construction=200 now default (was M=8 ef=100)

## [0.1.0] - 2025-XX-XX

Initial release.
```

---

## Git Tagging & Push

```bash
# After version bump commits
git add Cargo.toml pyproject.toml .claude/settings.json CHANGELOG.md
git commit -m "chore: release v0.2.0"

# Annotated tag with changelog excerpt
git tag -a "v0.2.0" -m "Release v0.2.0

- HNSW dynamic ef tuning
- WebSearchTool
- FFI call overhead -66%
"

# Push
git push origin main --tags
```

---

## Docker Build

```dockerfile
# Multi-stage: Rust builder + Python runtime
FROM rust:1.78-slim AS rust-builder
WORKDIR /app
COPY Cargo.toml Cargo.lock .cargo/ ./
COPY crates/ crates/
RUN cargo build --release --bin seahorse-router

FROM python:3.11-slim AS python-builder
COPY --from=rust-builder /app/target/wheels/ /wheels/
RUN pip install /wheels/*.whl

FROM python:3.11-slim
COPY --from=rust-builder /app/target/release/seahorse-router /usr/local/bin/
COPY --from=python-builder /usr/local/lib/python3.11/ /usr/local/lib/python3.11/
COPY python/ /app/python/
WORKDIR /app
EXPOSE 8080
CMD ["seahorse-router"]
```

```bash
docker build -t seahorse-agent:0.2.0 .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY seahorse-agent:0.2.0
```

---

## Release Checklist

- [ ] All tests pass (`pre_commit.sh`)
- [ ] Version bumped in `Cargo.toml`, `pyproject.toml`, `settings.json`
- [ ] `CHANGELOG.md` updated
- [ ] `cargo build --release --workspace` succeeds
- [ ] `maturin build --release` produces valid wheel
- [ ] Docker image builds and starts cleanly
- [ ] Git tag pushed
- [ ] GitHub Release created with CHANGELOG excerpt
