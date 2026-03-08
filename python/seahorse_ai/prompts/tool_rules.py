"""seahorse_ai.prompts.tool_rules — Clear, non-conflicting tool selection rules.

Each tool has exactly one primary trigger and one fallback.
Rules are ordered by specificity (most specific first).
"""
from __future__ import annotations

TOOL_RULES = """\
## Tool Selection Rules (follow in order)

### Memory & Internal Data
- If the user mentions something they told you before → `memory_search` FIRST.
- If the user asks to update/change a value they previously shared → `memory_search` + `memory_store`.
- If `memory_search` returns empty → inform user and optionally fall back to `web_search`.

### Real-time Public Data
- Stock market, commodity prices (gold/oil), cryptocurrency → `web_search` IMMEDIATELY.
- News, weather, live scores → `web_search` IMMEDIATELY.
- Do NOT check memory first for public market data.

### Database / Corporate Data
- ANY question about company sales, orders, customers → `database_schema` FIRST, then `database_query`.
- Never guess table or column names. Always inspect schema first.

### Calculations
- Any math, statistics, or data transformation → `python_interpreter`.

### Web Research
- Product comparisons, technical docs, general research → `web_search` then synthesize.
- Use `browser_scan` ONLY when web_search snippets are incomplete for a specific URL.

### Disambiguation Rule (CRITICAL)
- The word "ราคา" (price) alone is ambiguous:
  - If it's a product the user mentioned before → PRIVATE_MEMORY path (memory_search first)
  - If it's a public commodity (gold, stocks, crypto) → PUBLIC_REALTIME path (web_search)
"""
