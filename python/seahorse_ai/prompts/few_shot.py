"""seahorse_ai.prompts.few_shot — High-quality tool selection examples."""

from __future__ import annotations

FEW_SHOT_TOOL_EXAMPLES = """\
## Examples: Correct Behavior

**Q:** "How much is Package A?"
**Action:** memory_search("Package A price")
→ Found: "Package A costs 1,200 THB"
**Answer:** "Package A costs 1,200 THB." ← STOP HERE. Do NOT web_search.

---

**Q:** "How much is Package B?" (no memory result)
**Action:** memory_search("Package B price")
→ Empty result
**Answer:** "There is no price data for Package B in the system. \
Would you like to provide the price so I can save it?" ← Do NOT web_search.

---

**Q:** "Change it to 1,500 THB" (ambiguous — no product specified)
**Action:** memory_search("package price") to find all stored packages
→ Found: Package A (1,200), Package B (800)
**Answer:** "Which package do you mean?\n1. Package A (1,200 THB)\n\
2. Package B (800 THB)" ← Ask FIRST. Do not guess.

---

**Q:** "Change the price of Package A to 1,500 THB" (specific — no clarification needed)
**Action 1:** memory_search("Package A price") → find old value
**Action 2:** memory_store("Package A price is 1,500 THB") → save new value
**Answer:** "Updated! The new price for Package A is 1,500 THB."

---

**Q:** "ราคาทองคำวันนี้เท่าไหร่?"
**Action:** web_search("gold price today") IMMEDIATELY ← public market data

---

**Q:** "ตอนนี้ราคาเท่าไหร่?" (asked right after discussing Package A)
**Action:** memory_search("Package A price") — use conversation context
→ If found: answer immediately. Do NOT also web_search.

---

**Q:** "จำว่าฉันชอบกาแฟดำ"
**Action:** memory_store("User likes black coffee", importance=3) IMMEDIATELY.

---

**Q:** "ข่าวเทคโนโลยีล่าสุด"
**Action:** web_search("technology news today")
"""
