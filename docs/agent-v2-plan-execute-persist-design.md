# ออกแบบ Agent แบบ Plan → Execute → เก็บผล → ประเมิน → ทำซ้ำจนสำเร็จ (Cursor-style)

เอกสารนี้อธิบายว่า **ระบบ agent รุ่นใหม่ (รวมถึงแบบ Cursor)** ออกแบบยังไง และเสนอ **สถาปัตยกรรมสำหรับ Seahorse** ให้มีลำดับการทำงานแบบ: สร้าง plan → ทำตาม plan → เก็บคำตอบ/ผลลัพธ์ก่อนหน้า → ประเมินความสำเร็จ → ถ้ายังไม่สำเร็จให้ replan/ทำซ้ำจนบรรลุเป้าหมายหรือถึงขีดจำกัด

---

## 1. ระบบแบบ Cursor / Agent รุ่นใหม่ทำยังไง

### แนวคิดหลัก

- **ไม่ใช่แค่ “ถาม–ตอบครั้งเดียว”** แต่เป็น **ลูปที่มี state ค้างอยู่**:
  - มี **plan** (แผนงาน) ที่แตกงานเป็นขั้นตอน
  - **Execute** แต่ละขั้น แล้ว **เก็บผลลัพธ์** (artifact, ไฟล์, สรุป) ไว้
  - ใช้ผลที่เก็บมาเป็น **context รอบถัดไป**
  - มีการ **ประเมิน** ว่า “เป้าหมายบรรลุหรือยัง”
  - ถ้ายังไม่บรรลุ → **replan หรือทำขั้นถัดไป** โดยอ้างอิงผลก่อนหน้า
  - ทำซ้ำจน **สำเร็จตามที่ user ต้องการ** หรือถึง **ขีดจำกัด** (จำนวนรอบ, เวลา, token)

### Cursor (Plan Mode + Agent Mode)

- **Plan phase**: สร้าง plan (มักเป็น Markdown) — ระบุไฟล์, ขั้นตอน, อ้างอิง code
- **Execute phase**: ทำตาม plan (แก้ไฟล์, search, รันคำสั่ง)
- **เก็บผล**: บันทึก plan ลง workspace (เช่น `.cursor/plans/`), ผลจากการแก้/รันก็อยู่ในไฟล์และ terminal
- **ประเมิน**: รันเทส/ build — ถ้าไม่ผ่านถือว่า “ยังไม่สำเร็จ”
- **ทำซ้ำ**: ปรับ plan หรือแก้โค้ดต่อจนเทสผ่าน (iterate until tests pass)

ลักษณะสำคัญ: **state อยู่ที่ “สิ่งที่ทำไปแล้ว” (plan + ไฟล์ + ผลรัน)** ไม่ใช่แค่ข้อความในแชทอย่างเดียว

---

## 2. แนวทางที่ Agent รุ่นใหม่ (2024–2025) ใช้กัน

### 2.1 Plan – Execute – Reflect (ReAct ขยาย)

```
while not goal_achieved and under_budget:
    thought = LLM.reason(current_state, goal, past_observations)
    action = LLM.decide_action(thought, tools)
    observation = execute(action)
    state.update(observation)   # เก็บผล
    if should_reflect(state):
        reflection = LLM.reflect(state, goal)
        state.update(reflection)
```

- **Plan**: อาจเป็น strategy ชุดเดียว หรือ replan เมื่อเจอ dead end
- **Execute**: เรียก tool ได้หลายขั้น ผลแต่ละขั้นต้อง **persist** (เก็บใน state)
- **Reflect**: ดูผลที่เก็บไว้แล้ว “คิดใหม่” (ปรับแผน / เปลี่ยนวิธี) แล้วอัปเดต state

### 2.2 Reflexion-style (เรียนรู้จากความล้มเหลว)

- **Plan** → **Execute** → **Evaluate** (สำเร็จหรือไม่) → **Reflect** (วิเคราะห์ว่าผิดพลาดตรงไหน) → **Update Memory** (เก็บบทเรียน) → ลองใหม่
- “ความสำเร็จ” ต้องนิยามชัด (เช่น tests pass, user ยืนยัน, หรือ LLM judge)

### 2.3 State ที่ต้องมี (จาก Agent Architectures ที่ทันสมัย)

| ประเภท State | หน้าที่ |
|--------------|--------|
| **Conversation / Turn history** | บันทึก user prompt, assistant reasoning, tool calls, tool results (เหมือนที่ Seahorse มีอยู่) |
| **Working memory / Artifacts** | เก็บ “ผลลัพธ์ที่ได้จากแต่ละขั้น” — สรุปข้อความ, ลิงก์, ไฟล์ path, ผล query — เพื่อให้รอบถัดไปใช้ได้ |
| **Plan state** | แผนปัจจุบัน (ขั้นที่ทำแล้ว / ยังไม่ทำ), สาเหตุที่ replan (ถ้ามี) |
| **Goal & success criteria** | เป้าหมาย user + เงื่อนไข “สำเร็จ” (explicit หรือ implicit) |

### 2.4 Termination ที่ชัดเจน

- **Goal-based**: ประเมินแล้ว “บรรลุเป้าหมาย” → หยุด
- **Resource**: ครบ max_trials / max_steps / max_time / max_tokens → หยุด (อาจคืน partial result)
- **Safety**: error ติดกันหลายครั้ง, นโยบายความปลอดภัย → หยุดหรือ escalate

---

## 3. สถาปัตยกรรมที่เสนอสำหรับ Seahorse (ให้ทำแบบ Cursor / ทำซ้ำจนสำเร็จ)

### 3.1 ภาพรวม

เพิ่ม **outer loop “ทำซ้ำจนสำเร็จ”** ครอบ ReAct เดิม และเพิ่ม **state ที่เก็บผลระหว่างรอบ** กับ **success criteria**:

```
User request + goal/success_criteria
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Outer Loop (Plan–Execute–Persist–Evaluate)                     │
│                                                                  │
│  1. Plan (หรือ Replan)                                          │
│     • สร้าง/ปรับ plan จาก goal + ผลที่เก็บจากรอบก่อน (ถ้ามี)     │
│     • ใส่ plan ลง system message / working state                 │
│                                                                  │
│  2. Execute (ReAct ภายในหนึ่ง “trial”)                          │
│     • ReActExecutor.run() เหมือนเดิม                             │
│     • ทุก step: เรียก tool, เก็บ observation ลง messages         │
│                                                                  │
│  3. Persist (เก็บผลของ trial นี้)                               │
│     • สรุปผลของ trial (artifact summary)                         │
│     • เก็บลง Working Memory / Session State                      │
│     • รอบถัดไปจะได้ใช้ “สิ่งที่ทำไปแล้ว”                          │
│                                                                  │
│  4. Evaluate (ตรวจว่าบรรลุเป้าหมายหรือยัง)                       │
│     • ถ้ามี success_criteria (จาก user หรือ default) → ตรวจ      │
│     • อาจใช้ LLM เป็น judge หรือ rule-based (เช่น “มีคำตอบครบ”)  │
│                                                                  │
│  5. Decide                                                       │
│     • ถ้า success → return ผลลัพธ์                               │
│     • ถ้ายังไม่สำเร็จ และยังไม่เกิน max_trials → กลับไปขั้น 1      │
│     • ถ้าเกินขีดจำกัด → return ผลลัพธ์ที่ดีที่สุดที่ได้ + สถานะ   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 สิ่งที่ต้องเพิ่มใน Seahorse

| ส่วน | รายละเอียด |
|------|-------------|
| **Goal & Success criteria** | รับจาก request (เช่น `goal: str`, `success_criteria: list[str]` หรือ callback) หรือใช้ default เช่น “มีข้อความตอบที่สมเหตุสมผลและไม่ terminated” |
| **Working memory / Artifact store ต่อ session** | เก็บ “ผลสรุปของแต่ละ trial” (และถ้าต้องการ เก็บบาง tool outputs ที่สำคัญ) ให้รอบถัดไปอ่านได้ — อาจใช้ field ใน `AgentRequest`/state หรือเก็บใน Rust memory/DB ต่อ `session_id` |
| **Evaluate step** | หลัง ReActExecutor.run() เสร็จ เรียกโมดูล “evaluate”: รับ goal + success_criteria + result + (ถ้ามี) artifact summary แล้วคืน `success: bool`, optional `reason: str` |
| **Outer loop** | ใน ReActPlanner (หรือคลาสใหม่ PlanExecutePersistPlanner): ลูป 1–5 ด้านบน ใช้ `max_trials` (เช่น 3–5), `max_total_steps` หรือ `max_total_time` เป็น guard |
| **Replan logic** | เมื่อ evaluate ได้ “ยังไม่สำเร็จ” ให้สร้าง plan ใหม่โดยรับ “ผลที่ persist แล้ว” เป็น context (และถ้ามี Reflexion-style ก็ใส่ reflection จาก failure ด้วย) |

### 3.3 โครงสร้างข้อมูลที่แนะนำ (แบบย่อ)

```python
# ขยาย AgentRequest (หรือใช้ใน state)
class GoalSpec:
    goal: str                    # เป้าหมายหลัก
    success_criteria: list[str]  # เงื่อนไขสำเร็จ (optional)

class TrialArtifact:
    trial_id: int
    plan_summary: str
    steps_taken: int
    final_content: str
    tool_outputs_summary: list[str]  # สรุปผล tool ที่สำคัญ
    terminated: bool
    termination_reason: str | None

# หลังแต่ละ trial
class EvaluateResult:
    success: bool
    reason: str | None
    suggested_next: str | None   # สำหรับ replan
```

### 3.4 การเก็บผล “ก่อนหน้า” (Persist)

- **ในหน่วยความจำของ session (ใน Python)**  
  เก็บ `list[TrialArtifact]` ต่อ `session_id` หรือ `execution_id`  
  เวลา replan: ส่ง artifact รอบก่อน (หรือสรุป) เข้าไปใน system/user message เพื่อให้ LLM “รู้ว่าทำอะไรไปแล้ว”

- **ถ้าต้องการให้อยู่ข้าม request**  
  เก็บใน DB หรือ Rust-backed store (เช่น key = `session_id`, value = JSON ของ artifacts)  
  API ต้องส่ง `session_id` มาด้วย

- **แบบ Cursor**  
  “ผลก่อนหน้า” คือ plan + ไฟล์ที่แก้ + ผลรัน — ใน Seahorse อาจเทียบได้กับ “สรุปข้อความ + ชื่อ tool และผลที่ได้” แล้วเก็บใน Working Memory

### 3.5 โฟลว์ที่ได้

1. User ส่งคำถาม + (ถ้าต้องการ) goal / success_criteria  
2. **Plan**: สร้าง plan ครั้งแรก จาก goal + history  
3. **Execute**: รัน ReAct หนึ่ง trial ตาม plan, เก็บทุก observation ลง messages  
4. **Persist**: สร้าง `TrialArtifact` จากผลของ trial นี้, append ลง session state  
5. **Evaluate**: ตรวจจาก success_criteria ว่า “สำเร็จตามที่ user ต้องการ” หรือยัง  
6. ถ้าสำเร็จ → ส่งผลกลับ user  
7. ถ้ายังไม่สำเร็จ และยังไม่เกิน max_trials → **Replan** (ใช้ artifact รอบก่อนเป็น context) แล้วกลับไปขั้น 3  
8. ถ้าเกินขีดจำกัด → ส่งผลลัพธ์ที่ดีที่สุดที่ได้ + ข้อความว่า “ยังไม่บรรลุเป้าหมายตาม criteria”

ผลคือระบบจะ “วิเคราะห์แล้วสร้าง plan แล้วเก็บคำตอบที่ได้ก่อนหน้า แล้วทำแบบนี้ซ้ำจนเกิดความสำเร็จตามความต้องการของ user” (หรือจนถึงขีดจำกัด) ตรงกับที่ Cursor และ agent รุ่นใหม่ออกแบบกัน

---

## 4. ระดับการใช้ Token (Token Usage)

การทำแบบ Plan → Execute → Persist → Evaluate → ทำซ้ำจนสำเร็จ **ใช้ token มากขึ้นชัดเจน** เพราะมีหลาย trial และแต่ละ trial มี plan + ReAct + (ถ้าใช้ LLM) evaluate

### 4.1 เทียบกับระบบปัจจุบัน (One-shot ReAct)

| โหมด | โครงสร้าง | Token โดยประมาณ (ระดับ) |
|------|-----------|---------------------------|
| **ปัจจุบัน (Seahorse)** | Intent + (ถ้า strategist) Plan 1 ครั้ง + ReAct 1 รอบ (สูงสุด 15 steps) + synthesis | **1×** — ประมาณ 5k–50k tokens ต่อ request (ขึ้นกับความยาว history, จำนวน step, ขนาด tool results) |
| **แบบ Plan–Execute–Persist–Evaluate** | แต่ละ trial = Plan/Replan + ReAct เต็ม 1 รอบ + Persist (สรุป) + Evaluate (ถ้าใช้ LLM) | **2×–5×** หรือมากกว่า — ขึ้นกับจำนวน trial จริง |

### 4.2 แยกตามส่วน (ต่อ 1 request)

- **Plan / Replan (ต่อ trial)**  
  - ครั้งแรก: system + goal + history → สร้าง plan  
  - ครั้งถัดไป: goal + สรุปผล trial ก่อน (artifact summary) → สร้าง plan ใหม่  
  - โดยประมาณ: **~0.5k–3k input + 0.5k–2k output ต่อ trial**

- **Execute (ReAct 1 trial)**  
  - เทียบเท่ารัน ReAct ปัจจุบันหนึ่งครั้ง (สูงสุด 15 steps)  
  - โดยประมาณ: **~5k–50k tokens ต่อ trial** (เหมือน 1× ของปัจจุบัน)

- **Persist**  
  - สรุปผล trial (ข้อความสั้นๆ / structured) — ไม่จำเป็นต้องเรียก LLM ถ้าสรุปจาก result โดยตรง  
  - ถ้าใช้ LLM สรุป: **+1k–5k tokens ต่อ trial**

- **Evaluate**  
  - แบบ **rule-based** (เช่น ตรวจว่าไม่ terminated, มี content): **0 token**  
  - แบบ **LLM judge** (ส่ง goal + criteria + result ให้ LLM ตัดสิน): **~1k–5k tokens ต่อ trial**

รวมต่อ request (สมมติ 3 trials):

- **กรณีประหยัด**: Evaluate แบบ rule, Persist ไม่ใช้ LLM → ประมาณ **1.5×–3×** ของ one-shot (เพราะ ReAct 3 รอบ แต่ละรอบอาจหยุดก่อน 15 steps)  
- **กรณีเต็ม**: Plan 3 ครั้ง + ReAct 3 รอบ + Persist ด้วย LLM + Evaluate ด้วย LLM → **ประมาณ 3×–5×** ของ one-shot

### 4.3 ระดับโดยรวม (order of magnitude)

| สถานการณ์ | จำนวน trial | ระดับ token (เทียบ one-shot) | ตัวอย่างคร่าวๆ (ถ้า one-shot ≈ 20k tokens) |
|-----------|-------------|------------------------------|-------------------------------------------|
| สำเร็จ trial แรก | 1 | **~1×** | ~20k |
| ต้อง 2 trials | 2 | **~2×** | ~40k |
| ต้อง 3 trials | 3 | **~2.5×–3.5×** | ~50k–70k |
| max_trials=5 ครบ | 5 | **~4×–5×** | ~80k–100k |

ดังนั้น **การทำแบบนี้ใช้ token ระดับ 2×–5×** ของการรัน ReAct แบบครั้งเดียว (และอาจเกิน 5× ถ้าใช้ LLM ในการ persist/evaluate ทุก trial และมีหลาย trial)

### 4.4 วิธีควบคุมการใช้ token

- **จำกัดจำนวน trial**: ตั้ง `max_trials = 2` หรือ `3` — ลดโอกาสใช้ token เกิน 3×–4×  
- **จำกัด token รวมต่อ request**: ตั้ง `max_total_tokens` (หรือ `max_total_input_tokens`) แล้วหยุด outer loop เมื่อเกิน — คืนผลลัพธ์ที่ดีที่สุดที่ได้จนถึงตอนนั้น  
- **Persist แบบไม่ใช้ LLM**: สรุป artifact จาก `result.content` + รายการ tool ที่เรียก + สถานะ terminated โดยไม่เรียก LLM เพิ่ม  
- **Evaluate แบบ rule ก่อน**: ใช้ rule (มีคำตอบ, ไม่ terminated) เป็นหลัก และเรียก LLM judge เฉพาะเมื่อไม่แน่ใจหรือให้ user ตั้งค่า  
- **ย่อ context ที่ส่งเข้า replan**: ส่งเฉพาะ **artifact summary** (ข้อความสั้นๆ ต่อ trial) ไม่ส่ง full message history ของ trial ก่อน  
- **ใช้โมเดลเล็กสำหรับงานเบา**: ใช้โมเดลถูก/เร็วสำหรับ Plan หรือ Evaluate ถ้าไม่จำเป็นต้องใช้โมเดลใหญ่

ถ้าตั้ง `max_trials=3`, Evaluate แบบ rule, Persist แบบไม่ใช้ LLM และย่อ artifact ให้สั้น **ระดับ token โดยรวมจะอยู่ที่ประมาณ 2×–3×** ของ one-shot ซึ่งยังอยู่ในระดับที่รับได้สำหรับ use case ที่ต้องการ “ทำซ้ำจนสำเร็จ”

---

## 5. Design Decisions ที่ทำให้ Pattern นี้มีประสิทธิภาพสูงกว่า PEPE Loop เดิม

PEPE loop (Plan–Execute–Persist–Evaluate) แบบง่ายที่ออกแบบในหัวข้อ 3 ยังเป็น **sequential single-agent loop** ทุก trial รันทีละ task เดียว, critic อยู่ในตัว, และ context window โตขึ้นทุกรอบ ส่วนนี้อธิบาย design decisions 4 ข้อที่ยกระดับขึ้นเป็น **parallel multi-agent architecture** (ตามแผนภาพ orchestrator → subagents → critic → shared memory) ซึ่งเหมาะกับ Seahorse ที่มี Rust core + Tokio + MessageBus อยู่แล้ว

```
                     goal + context
                          │
                          ▼
                   ┌─────────────┐
                   │ orchestrator │  ← intent classifier (lightweight, ไม่ใช้ LLM เต็ม)
                   │  decompose   │  ← task decomposer (output = dependency graph)
                   │  route       │
                   └──┬──┬──┬──┬─┘
                      │  │  │  │
            ┌─────────┘  │  │  └─────────┐
            ▼            ▼  ▼            ▼
       ┌─────────┐ ┌─────────┐     ┌─────────┐
       │subagent │ │subagent │ ... │subagent │  ← แต่ละตัวมี context window แยก
       │  A      │ │  B      │     │  N      │  ← รัน parallel ได้ถ้า independent
       └────┬────┘ └────┬────┘     └────┬────┘
            │           │               │
            └─────┬─────┴───────────────┘
                  ▼
           ┌────────────┐    pass
           │critic agent│ ─────────→ output
           │verify·score│
           │reject      │
           └─────┬──────┘
                 │ fail → replan (targeted, เฉพาะ subagent ที่ fail)
                 ▼
        ┌──────────────────┐
        │ shared memory    │
        │ HNSW · KV · สรุป │
        └──────────────────┘
```

### 5.1 Orchestrator Layer: Lightweight Intent + Dependency Graph Decomposition

**ปัญหาของ PEPE เดิม:** Plan ใช้ LLM เต็มรูปแบบทุกครั้ง (แม้แค่ทักทาย) และ plan ออกมาเป็น ordered list ทำให้ subtask ทุกตัวต้องรันตามลำดับ

**Design decision:**

- **Intent classifier แยกเป็น lightweight component** — ใช้ keyword matching / regex / small model (เช่น FastPath ที่ Seahorse มีอยู่) ไม่ใช้ LLM เต็มสำหรับ routing ทำให้ตัดสินใจ route ได้ใน **< 50ms** ก่อนเข้า decomposer
- **Task decomposer output เป็น dependency graph ไม่ใช่ ordered list** — แต่ละ subtask ระบุ `depends_on: list[subtask_id]` ทำให้ orchestrator รู้ทันทีว่า subtask ไหน independent (ไม่มี dependency ต่อกัน) และสั่ง parallel ได้เลย

```python
class SubtaskNode(Struct):
    id: str
    description: str
    assigned_agent: str
    depends_on: list[str]     # ว่าง = independent, รันพร้อมกันได้
    status: str               # pending | running | done | failed

class DecompositionGraph(Struct):
    goal: str
    nodes: list[SubtaskNode]
```

**ทำไมดีกว่า:** routing เร็วขึ้น 10×+ (ไม่ต้องรอ LLM สำหรับ classify) และ subtask ที่ independent ได้รัน parallel ทันทีแทนที่จะรอตามลำดับ

### 5.2 Subagent Isolation: Context Window แยก + True Parallelism

**ปัญหาของ PEPE เดิม:** ทุก trial ใช้ messages list เดียวกัน → context window โตขึ้นทุกรอบ → ช้าลง + แพงขึ้น + เสี่ยง context overflow

**Design decision:**

- **แต่ละ subagent มี context window ของตัวเอง** — ไม่แชร์ history กับ subagent อื่น ได้รับแค่ goal ของ subtask ตัวเอง + relevant context จาก shared memory (ถ้าจำเป็น)
- **รัน parallel ได้จริงใน Tokio** — subagent ที่ independent (ไม่มี depends_on) ถูก spawn เป็น concurrent tasks ผ่าน `tokio::spawn` + `mpsc::channel` สำหรับ result collection ตรง map กับสถาปัตยกรรม Seahorse ที่มีอยู่แล้ว (scheduler + worker + MessageBus)
- **ผลลัพธ์ของแต่ละ subagent ถูก compress ก่อนส่งกลับ** — orchestrator ไม่ได้รับ full messages ของ subagent กลับมา ได้รับแค่ structured result (สรุป + status) ทำให้ context ของ orchestrator ไม่ blow up

```
Independent subtasks A, B, C (ไม่มี dependency ต่อกัน):

  tokio::spawn(subagent_A.run(subtask_A))  ──┐
  tokio::spawn(subagent_B.run(subtask_B))  ──┤── รัน parallel
  tokio::spawn(subagent_C.run(subtask_C))  ──┘
                                               │
                      collect results via channel
                                               ▼
                              orchestrator merges
```

**ทำไมดีกว่า:** 3 subtask ที่ independent ใช้เวลาเท่ากับ 1 subtask (latency) แทนที่จะเป็น 3× และ context ของแต่ละ subagent เล็ก → ทั้งเร็วกว่าและถูกกว่า

### 5.3 Critic Isolation: ห้ามเห็น Chain-of-Thought ของ Actor

**นี่คือ design rule ที่สำคัญที่สุดของทั้ง pattern**

**ปัญหาของ PEPE เดิม:** ขั้น Evaluate ใน PEPE รับ full messages (รวม chain-of-thought ของ ReAct) เข้ามาตัดสิน → critic ถูก **anchored** ไปตาม reasoning ของ actor → bias สูง, มักจะ pass ทั้งที่ผลลัพธ์จริงยังไม่ดีพอ

**Design decision:**

- **Critic ต้องไม่เห็น chain-of-thought ของ actor เลย** — ให้เห็นแค่ 3 อย่าง:
  1. **Output** (ผลลัพธ์สุดท้ายของ subagent)
  2. **Original goal** (เป้าหมายเดิมของ user)
  3. **Success criteria** (เงื่อนไขสำเร็จ)

- **Verdict แยกเป็น 3 ระดับ ไม่ใช่แค่ pass/fail:**

| Verdict | ความหมาย | ผลต่อ flow |
|---------|----------|------------|
| **pass** | ผลลัพธ์ตรงตาม criteria ทุกข้อ | → ส่ง output กลับ user |
| **partial** | ผลลัพธ์บางส่วนผ่าน บางส่วนยังไม่ครบ | → **targeted replan** เฉพาะ subagent ที่ fail ไม่ต้อง redo ทั้งหมด |
| **reject** | ผลลัพธ์ผิดทิศหรือไม่ตอบโจทย์เลย | → replan ใหม่ทั้งหมดจาก orchestrator |

```python
class CriticVerdict(Struct):
    verdict: str                    # "pass" | "partial" | "reject"
    passed_criteria: list[str]      # criteria ที่ผ่านแล้ว
    failed_criteria: list[str]      # criteria ที่ยังไม่ผ่าน
    failed_subtasks: list[str]      # subtask_id ที่ต้อง replan (กรณี partial)
    reason: str                     # อธิบายสั้นๆ ว่าทำไมถึงตัดสินแบบนี้
```

**ทำไมดีกว่า:** critic ตัดสินจาก output จริงโดยไม่ถูก bias จาก reasoning process + partial verdict ทำให้ replan เฉพาะจุดที่ fail ได้ → **ประหยัด token 50–70%** เทียบกับ redo ทุก subtask ใหม่ทั้งหมด

### 5.4 3-Tier Memory: แก้ปัญหา Context Burn โดยตรง

**ปัญหาของ PEPE เดิม:** เก็บผลทุกรอบใน `list[TrialArtifact]` แล้ว inject กลับเข้า context ทั้งหมด → context โตขึ้นทุก trial → "context burn" (token เพิ่มแบบ O(n) ต่อ trial)

**Design decision: แบ่ง memory เป็น 3 tier**

| Tier | ชื่อ | หน้าที่ | Lifetime | ตำแหน่งใน Seahorse |
|------|------|--------|----------|-------------------|
| **Tier 1: Scratchpad** | per-subagent working memory | chain-of-thought, tool calls, observations ระหว่างรัน | **ทิ้งหลังจบ subtask** — ไม่ persist ข้ามรอบ | อยู่ใน messages list ของ ReActExecutor (เหมือนเดิม) |
| **Tier 2: Structured KV** | plan state + result summaries | เก็บ plan, subtask status, compressed results ของแต่ละ trial | **persist ข้าม iteration** — ใช้จนจบ session | `DashMap<String, Value>` ใน Rust หรือ Python dict ต่อ session_id |
| **Tier 3: HNSW Vector** | long-term relevant context | ดึง relevant past context ก่อน replan (เช่น "เคย fail เรื่องนี้ด้วยวิธีนี้") | **persist ข้าม session** — เรียนรู้จากประสบการณ์ | `AgentMemory` (HNSW) ที่ Seahorse มีอยู่แล้ว |

**กฎการ inject memory กลับเข้า context:**

- Memory snapshot ที่ inject กลับเข้า context window ต้อง **ไม่เกิน 20% ของ window size**
  - เช่น ถ้า window = 128k tokens → inject ได้สูงสุด ~25k tokens
  - ถ้า window = 32k tokens → inject ได้สูงสุด ~6k tokens
- ต้องเป็น **delta เท่านั้น** (เฉพาะสิ่งที่เปลี่ยนหรือเพิ่มจากรอบก่อน) **ไม่ใช่ full history**
  - รอบ 1: inject plan + goal
  - รอบ 2: inject "subtask A ผ่านแล้ว, subtask B fail เพราะ X" (delta) ไม่ใช่ "plan + ผล A ทั้งหมด + ผล B ทั้งหมด"
- **Tier 3 ใช้ semantic search** (HNSW) ก่อน inject — ดึงแค่ top-k ที่ relevant กับ subtask ที่ต้อง replan ไม่ใช่ dump ทุกอย่าง

```
Context composition ก่อนเริ่มแต่ละ subagent:

┌──────────────────────────────────────────┐
│ System prompt                      ~5%   │
│ Goal + success criteria            ~5%   │
│ Subtask description                ~5%   │
│ Tier 2 delta (plan state summary)  ~10%  │  ← ≤ 20% รวม
│ Tier 3 relevant memories (top-k)   ~10%  │
│ ─────────────────────────────────────── │
│ Available for ReAct execution      ~65%  │  ← ที่เหลือให้ subagent ทำงาน
└──────────────────────────────────────────┘
```

**ทำไมดีกว่า:** context window ไม่โตตามจำนวน trial (เพราะ Tier 1 ถูกทิ้ง, Tier 2 ส่งแค่ delta, Tier 3 ส่งแค่ relevant) → สามารถทำ 5+ trials โดย context ไม่ blow up → **token per trial เกือบคงที่** แทนที่จะเพิ่มแบบ O(n)

### 5.5 สรุป: ผลรวมของ 4 Design Decisions

| Design Decision | ปัญหาที่แก้ | ผลที่ได้ |
|----------------|------------|---------|
| Lightweight intent + dependency graph | Routing ช้า + subtask ต้องรันตามลำดับ | Route < 50ms + parallel subtasks |
| Subagent isolation | Context โตทุกรอบ + ไม่ parallel ได้จริง | Context เล็ก + true parallelism via Tokio |
| Critic ไม่เห็น chain-of-thought + 3-level verdict | Bias จาก actor reasoning + redo ทั้งหมดเมื่อ fail | Unbiased evaluation + targeted replan เฉพาะจุดที่ fail |
| 3-tier memory + 20% cap + delta-only | Context burn O(n) ต่อ trial | Token per trial เกือบคงที่ + เรียนรู้ข้าม session |

**ผลรวม:** เมื่อ apply ทั้ง 4 ข้อ token usage ของ multi-trial ลดจาก **O(n × full_context)** เหลือประมาณ **O(n × subtask_context)** (ซึ่ง subtask_context << full_context เพราะ isolation + delta inject) และ latency ลดจาก **sequential** เป็น **parallel** สำหรับ subtask ที่ independent → ใช้ token โดยรวมใกล้เคียง 2×–3× ของ one-shot แม้จะมี 3–5 trials

---

## 6. สรุป

- **Cursor / agent รุ่นใหม่**: ใช้ลำดับ **Plan → Execute → เก็บผล (persist) → ประเมิน (evaluate) → ทำซ้ำจนสำเร็จหรือถึงขีดจำกัด**  
- **State**: ต้องมี conversation history + **working memory / artifact** ที่เก็บผลแต่ละขั้น/แต่ละ trial  
- **Termination**: ต้องมี **goal-based** (success criteria) + **resource/safety limits**  
- **Seahorse**: เพิ่ม outer loop + success criteria + การ persist ผลแต่ละ trial + evaluate แล้ว replan ได้ จะทำให้ระบบ “ทำแบบ Cursor” ได้ — คือวิเคราะห์ สร้าง plan เก็บคำตอบที่ได้ก่อนหน้า และทำซ้ำจนสำเร็จตามที่ user ต้องการ

ไฟล์นี้ใช้เป็น spec สำหรับ implement ใน `seahorse_ai.planner` (และถ้าต้องการ session store ใน Rust/DB ในภายหลัง) ได้เลย
