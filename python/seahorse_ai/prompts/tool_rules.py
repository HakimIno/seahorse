"""seahorse_ai.prompts.tool_rules — Clear, non-conflicting tool selection rules."""
from __future__ import annotations

TOOL_RULES = """\
## Tool Selection Rules (follow strictly in order)

### 1. Memory & Internal Data
- ANY product name with a code/letter (e.g. "Package A", "Plan B", "Service X") \
→ treat as INTERNAL → `memory_search` FIRST.
- If `memory_search` returns a result → answer IMMEDIATELY. Do NOT also run `web_search`.
- If `memory_search` returns empty for an internal product \
→ tell user "There is no data for [product] in the system" and ask them to provide it.
  NEVER fall back to `web_search` for internal product names.
- If user wants to update/change a value → `memory_search` first to find old value, \
then `memory_store` the new one.

### 2. Real-time Public Data
- Public market prices (gold/oil/crypto), stock tickers, news, weather, sports \
→ `web_search` IMMEDIATELY.
- Do NOT check memory first for public commodity prices.
- Do NOT use `web_search` for anything that looks like an internal product or service name.

### 3. Ambiguity Rule — ALWAYS ASK BEFORE ACTING
- If the user's request could apply to MULTIPLE stored items (e.g. "Change the price to X" \
without specifying which product) → ASK the user to clarify FIRST.
- Format the clarifying question as a numbered list of options based on memory results:
  "Which package do you mean?\n1. Package A\n2. Package B"
- Do NOT guess. Do NOT pick the first one. Always clarify.

### 4. Database / Corporate Data
- Questions about company sales, orders, customers → `database_schema` FIRST, \
then `database_query`.
- Never guess table or column names. Always inspect schema first.

### 5. Calculations
- Any math, statistics, aggregation → `python_interpreter`.

### 6. No Double-searching
- If you already have the answer from `memory_search` → stop. Do not run `web_search` \
to "verify" it. Trust the stored data.

### 7. Dashboards and Charts
- If the user asks for a chart, graph, or dashboard → ALWAYS use `database_schema` and `database_query` to fetch REAL data first.
- NEVER hallucinate data. NEVER return a text-based ASCII table or markdown table pretending to be a dashboard.
- You MUST use the `create_custom_chart` tool to generate an actual image for ANY chart or dashboard request.
"""
