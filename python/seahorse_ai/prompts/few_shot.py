"""seahorse_ai.prompts.few_shot — High-quality tool selection examples."""
from __future__ import annotations

FEW_SHOT_TOOL_EXAMPLES = """\
## Examples: Correct Behavior

**Q:** "Package A ราคาเท่าไหร่?"
**Action:** memory_search("Package A price")
→ Found: "Package A ราคา 1,200 บาท"
**Answer:** "Package A ราคา 1,200 บาท ครับ" ← STOP HERE. Do NOT web_search.

---

**Q:** "Package B ราคาเท่าไหร่?" (no memory result)
**Action:** memory_search("Package B price")
→ Empty result
**Answer:** "ไม่มีข้อมูลราคา Package B ในระบบครับ \
คุณต้องการแจ้งราคาเพื่อให้ฉันบันทึกไว้ไหม?" ← Do NOT web_search.

---

**Q:** "เปลี่ยนเป็น 1,500 บาท" (ambiguous — no product specified)
**Action:** memory_search("package price") to find all stored packages
→ Found: Package A (1,200), Package B (800)
**Answer:** "คุณหมายถึง Package ไหนครับ?\n1. Package A (1,200 บาท)\n\
2. Package B (800 บาท)" ← Ask FIRST. Do not guess.

---

**Q:** "เปลี่ยนราคา Package A เป็น 1,500 บาท" (specific — no clarification needed)
**Action 1:** memory_search("Package A price") → find old value
**Action 2:** memory_store("Package A ราคา 1,500 บาท") → save new value
**Answer:** "อัปเดตแล้วครับ Package A ราคาใหม่คือ 1,500 บาท"

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
