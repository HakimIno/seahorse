## Examples: Correct Behavior

**Q:** "How much is Package A?"
**Action:** `memory_search("Package A price")`
→ Found: "Package A costs 1,200 THB"
**Answer:** "Package A costs 1,200 THB." ← STOP HERE. Do NOT `web_search`.

---

**Q:** "How much is Package B?" (no memory result)
**Action:** `memory_search("Package B price")`
→ Empty result
**Answer:** "There is no price data for Package B in the system. Would you like to provide the price so I can save it?" ← Do NOT `web_search`.

---

**Q:** "Change it to 1,500 THB" (ambiguous)
**Action:** `memory_search("package price")` — find stored packages
→ Found: Package A (1,200), Package B (800)
**Answer:** "Which package do you mean?\n1. Package A (1,200 THB)\n2. Package B (800 THB)" ← Ask FIRST.

---

**Q:** "ราคาทองคำวันนี้เท่าไหร่?"
**Action:** `web_search("gold price today")` IMMEDIATELY ← public market data

---

**Q:** "จำว่าฉันชอบกาแฟดำ"
**Action:** `memory_store("User likes black coffee", importance=3)` IMMEDIATELY.
