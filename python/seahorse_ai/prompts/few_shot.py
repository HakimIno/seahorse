"""seahorse_ai.prompts.few_shot — High-quality tool selection examples.

Few-shot examples are the most effective way to teach an LLM behavior.
Each example shows the expected reasoning pattern, NOT just the answer.
"""
from __future__ import annotations

FEW_SHOT_TOOL_EXAMPLES = """\
## Examples: Correct Tool Selection

**Q:** "Seahorse Pro ราคาเท่าไหร่?"
**Thinking:** The user asked about "Seahorse Pro" — this is an internal product \
the user may have mentioned before. Check memory first.
**Action:** memory_search("Seahorse Pro price")
→ If found in memory: Answer with stored price.
→ If empty: Tell user "I don't have this stored. Please tell me the price and I'll remember it."

---

**Q:** "ราคาทองคำวันนี้เท่าไหร่?"
**Thinking:** Gold price is public market data that changes daily. Memory won't have this.
**Action:** web_search("gold price today Thailand") IMMEDIATELY

---

**Q:** "เปลี่ยนราคา Seahorse Pro เป็น 750 บาท"
**Thinking:** User wants to update a stored value. Need to find the old one first.
**Action 1:** memory_search("Seahorse Pro price")
**Action 2:** If found, memory_store("Seahorse Pro ราคา 750 บาท") and confirm update.

---

**Q:** "ลูกค้ารายไหนซื้อสินค้ามากที่สุดในเดือนนี้?"
**Thinking:** This requires corporate database data, not web or memory.
**Action 1:** database_schema() to find customer and order table names.
**Action 2:** database_query("SELECT customer_id, SUM(...) FROM orders ...")

---

**Q:** "จำไว้ว่าฉันชอบกาแฟดำ"
**Thinking:** User wants to store a personal preference.
**Action:** memory_store("User likes black coffee", importance=3) IMMEDIATELY.

---

**Q:** "ข่าวเทคโนโลยีล่าสุดมีอะไรบ้าง?"  
**Thinking:** Current news requires real-time web data.
**Action:** web_search("technology news today") IMMEDIATELY.
"""
