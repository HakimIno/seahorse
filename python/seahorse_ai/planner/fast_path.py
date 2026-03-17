"""seahorse_ai.planner.fast_path — Structured Intent Router.

Replaces the keyword hard-code approach with a single LLM call that returns
structured JSON: {intent, action, entity, needs_clarification}.

For simple actions (STORE, QUERY, GREET), the Fast Path executes the tool
directly without entering the ReAct loop — reducing latency from ~12s to ~3s.

Phase 2 upgrade: _handle_store uses LLM MemoryExtractor (no regex splitting).
Falls back to regex if extractor unavailable.

Complex actions (SEARCH_WEB, SQL, CHAT, CLARIFY) fall through to ReAct.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from seahorse_ai.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)

# Standardize conversation context window
_HISTORY_WINDOW = 4


@dataclass
class StructuredIntent:
    """Result of structured intent classification."""

    intent: str = "GENERAL"  # GENERAL|PUBLIC_REALTIME|PRIVATE_MEMORY|DATABASE|FOOTBALL
    action: str = "CHAT"  # STORE|QUERY|UPDATE|DELETE|SEARCH_WEB|SQL|GREET|CHAT|CLARIFY|FOOTBALL_INTEL
    entity: str | None = None  # The key data to store/search
    needs_clarification: bool = False  # True if ambiguous
    complexity: int = 3  # 1-5 (1: Easy/Greetings, 5: Multi-agent project)
    tone: str = "PROFESSIONAL"  # PROFESSIONAL | CASUAL
    raw_category: str = ""  # Legacy field for telemetry backward compatibility


# Actions that bypass ReAct tools but still generate natural responses
_FAST_ACTIONS = frozenset({"STORE", "QUERY", "GREET", "CHAT", "SEARCH_WEB", "FOOTBALL_INTEL", "POLARS_ANALYSIS"})

# (Removed hardcoded _GREETINGS and _CHAT_FALLBACKS arrays)

STRUCTURED_INTENT_PROMPT = """\
Analyze the user query and return ONLY valid JSON (no markdown, no explanation).

Fields:
- "intent": one of GENERAL, PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE, ANALYSIS, FOOTBALL
- "action": one of STORE, QUERY, UPDATE, DELETE, SEARCH_WEB, SQL, GREET, CHAT, CLARIFY, FOOTBALL_INTEL
- "entity": the key data to store/search/update (string or null)
- "needs_clarification": true if the request is ambiguous
- "complexity": 1-5 (Integer)
- "tone": "PROFESSIONAL" or "CASUAL"
    - 1-2: Simple facts, greetings, or basic storage (Fast Path).
    - 3-5: Requires deep analysis, SQL, or multi-step reasoning (ReAct Loop).

Rules:
- Simple greetings → {{"action":"GREET","complexity":1}}
- "Save/Remember X" → {{"action":"STORE","complexity":2}}
- "What is [internal fact]" → {{"action":"QUERY","complexity":2}}
- ANY analysis (Polars/SQL/Charts) → {{"complexity":3+, "action":"SQL"}}
- Simple chart request (e.g., "สร้างกราฟยอดขาย") → {{"complexity":3, "action":"SQL"}}
- Deep research or projects → {{"complexity":4+}}
- Football/Spec betting (e.g., "ราคาบอล", "Value", "xG") → {{"intent":"FOOTBALL", "action":"FOOTBALL_INTEL", "complexity":2}}


Conversation history (if any):
{history_summary}

User query: "{query}"
"""


async def classify_structured_intent(
    query: str,
    llm_backend: object,
    history: list[Message] | None = None,
) -> StructuredIntent:
    """Classify intent with structured output in 1 LLM call.

    Returns a StructuredIntent with action, entity, and clarification flag.
    Falls back to GENERAL/CHAT on any error.
    """
    from seahorse_ai.prompts.intent import (
        MEMORY_KEYWORDS,
        REALTIME_KEYWORDS,
        _is_greeting,
    )

    q_lower = query.lower().strip()

    # Tier 0: Greeting fast-path (0 LLM calls)
    if _is_greeting(q_lower):
        return StructuredIntent(
            intent="GENERAL",
            action="GREET",
            complexity=1,
            raw_category="GENERAL",
        )

    # Tier 1: Keyword-based early routing (0 LLM calls)
    analysis_keywords = (
        "กราฟ", "chart", "plot", "polars", "วิเคราะห์", "สรุป", "table", "ตาราง", 
        "เปรียบเทียบ", "สถิติ", "เฉลี่ย", "เปอร์เซ็นต์", "%", "compare", "statistics"
    )
    football_keywords = (
        "ราคาบอล", "บอลวันนี้", "วิเคราะห์บอล", "ทีเด็ด", "football odds", "soccer odds",
        "คะแนน xg", "ตัวเจ็บ", "ไลน์อัพ", "lineup", "value", "ความได้เปรียบ"
    )
    is_analysis = any(k.lower() in q_lower for k in analysis_keywords)
    is_football = any(k.lower() in q_lower for k in football_keywords)

    if is_football and not is_analysis:
        return StructuredIntent(
            intent="FOOTBALL",
            action="FOOTBALL_INTEL",
            complexity=2,
            raw_category="FOOTBALL",
        )

    if any(k.lower() in q_lower for k in REALTIME_KEYWORDS) and not is_analysis:
        return StructuredIntent(
            intent="PUBLIC_REALTIME",
            action="SEARCH_WEB",
            complexity=3,
            raw_category="PUBLIC_REALTIME",
        )

    if any(k.lower() in q_lower for k in MEMORY_KEYWORDS) and not is_analysis:
        return StructuredIntent(
            intent="PRIVATE_MEMORY",
            action="QUERY",
            complexity=2,
            raw_category="PRIVATE_MEMORY",
        )

    # Tier 2: Single LLM call for semantic/ambiguous cases
    history_summary = ""
    if history:
        recent = [m for m in history[-6:] if m.role in ("user", "assistant") and m.content]
        if recent:
            history_summary = "\n".join(f"- {m.role}: {(m.content or '')[:100]}" for m in recent)

    prompt = STRUCTURED_INTENT_PROMPT.format(
        query=query,
        history_summary=history_summary or "(no history)",
    )

    try:
        result = await llm_backend.complete(  # type: ignore[union-attr]
            [Message(role="user", content=prompt)], tier="fast"
        )
        logger.info("structured_intent raw result: %r", result)

        # Handle both dict and string results
        data = result
        if isinstance(result, dict):
            # If Content is already a dict, don't parse it as string
            data_content = result.get("content")
            if isinstance(data_content, str):
                data = _robust_json_load(data_content)
            elif isinstance(data_content, dict):
                data = data_content
        else:
            data = _robust_json_load(str(result))

        si = StructuredIntent(
            intent=data.get("intent", "GENERAL").upper(),
            action=data.get("action", "CHAT").upper(),
            entity=data.get("entity"),
            needs_clarification=data.get("needs_clarification", False),
            complexity=int(data.get("complexity", 3)),
            tone=data.get("tone", "PROFESSIONAL").upper(),
        )
        # Set legacy category
        si.raw_category = si.intent
        logger.info(
            "structured_intent: intent=%s action=%s entity=%r clarify=%s",
            si.intent,
            si.action,
            si.entity,
            si.needs_clarification,
        )
        return si

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("structured_intent parse error: %s", exc)
        # Fallback: use keyword-based classification
        from seahorse_ai.prompts.intent import (
            MEMORY_KEYWORDS,
            REALTIME_KEYWORDS,
        )

        for kw in MEMORY_KEYWORDS:
            if kw.lower() in q_lower:
                return StructuredIntent(
                    intent="PRIVATE_MEMORY",
                    action="QUERY",
                    raw_category="PRIVATE_MEMORY",
                )
        for kw in REALTIME_KEYWORDS:
            if kw.lower() in q_lower:
                return StructuredIntent(
                    intent="PUBLIC_REALTIME",
                    action="SEARCH_WEB",
                    raw_category="PUBLIC_REALTIME",
                )
        # Default to CHAT (slow path) for everything else, including mocks
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")

    except Exception as exc:  # noqa: BLE001
        logger.error("structured_intent failed: %s", exc)
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")


class FastPathRouter:
    """Execute simple actions directly — bypass the ReAct loop.

    Handles STORE, QUERY, GREET, and CHAT without the slow ReAct executor overhead.
    Complex actions (SEARCH_WEB, SQL, CLARIFY, UPDATE) fall through.
    """

    def __init__(self, tools: object, llm_backend: object = None) -> None:
        self._tools = tools
        self._llm = llm_backend

    async def try_route(
        self,
        si: StructuredIntent,
        agent_id: str,
        prompt: str,
        history: list[Message] | None = None,
    ) -> AgentResponse | None:
        """Try to handle via fast path. Returns None if ReAct loop needed."""
        if si.needs_clarification:
            return None  # Let ReAct + LLM ask clarifying question

        if si.action not in _FAST_ACTIONS:
            return None  # Complex → ReAct loop

        start_t = time.perf_counter()

        if si.action == "GREET":
            return await self._handle_conversational(prompt, history, start_t, tone=si.tone)

        if si.action == "CHAT":
            if si.complexity <= 2:
                return await self._handle_conversational(prompt, history, start_t, tone=si.tone)
            return None  # Complexity 3+ → ReAct or Auto-Seahorse

        if si.action == "STORE" and si.entity:
            return await self._handle_store(si.entity, agent_id)

        if si.action == "QUERY" and si.entity:
            return await self._handle_query(si.entity, agent_id, history)

        if si.action == "SEARCH_WEB":
            # Pass the entity (if any) or prompt to query handler
            search_term = si.entity if si.entity else prompt
            return await self._handle_web_search(search_term, prompt, history, start_t)

        if si.action == "POLARS_ANALYSIS":
            return await self._handle_polars_analysis(prompt, history, start_t)

        if si.action == "FOOTBALL_INTEL":
            return await self._handle_football_intel(prompt, history, start_t)

        return None

    async def _handle_conversational(
        self, prompt: str, history: list[Message] | None, start_t: float, tone: str = "PROFESSIONAL"
    ) -> AgentResponse:
        """Process greetings and simple chat queries fully via the fast model."""
        today = datetime.date.today().strftime("%A, %B %d, %Y")

        # Select persona based on tone
        if tone == "CASUAL":
            system_msg = (
                "You are Seahorse AI, but in a friendly, casual, and slightly humorous mode. "
                "You are chatting with a friend. Use emojis, be warm, and keep it light. "
                f"Today's date: {today}. "
                "Reply in the user's language."
            )
        else:
            system_msg = (
                "You are Seahorse AI, an intelligent business agent. "
                "You are professional, precise, and helpful. "
                f"Today's date: {today}. "
                "Answer politely, concisely, and naturally in the user's language."
            )

        msgs = [Message(role="system", content=system_msg)]
        if history:
            # OPTIMIZATION: Truncate history for greetings.
            # Usually only need last turns to maintain flow without token waste.
            msgs.extend(history[-_HISTORY_WINDOW:])
        msgs.append(Message(role="user", content=prompt))

        try:
            # Use the 'fast' tier (gemini-3.1-flash-lite) for extreme efficiency
            res = await self._llm.complete(msgs, tier="fast")
            content = str(res.get("content", res) if isinstance(res, dict) else res)
        except Exception as e:
            logger.error(f"Fast chat fallback error: {e}")
            content = "Sorry, I encountered an issue processing that."

        return AgentResponse(
            content=content,
            steps=1,
            elapsed_ms=int((time.perf_counter() - start_t) * 1000),
        )

    async def _handle_web_search(
        self, search_term: str, prompt: str, history: list[Message] | None, start_t: float
    ) -> AgentResponse | None:
        """Fast-path for simple web searches bypassing full planner."""
        try:
            # Execute tool directly
            raw_result = await self._tools.call("web_search", {"query": search_term})

            today = datetime.date.today().strftime("%A, %B %d, %Y")

            # Synthesize answer using fast model
            msgs = [
                Message(
                    role="system",
                    content=(
                        "You are Seahorse AI, an expert news anchor and researcher. "
                        f"Today's date: {today}. "
                        "Read the provided search results carefully. Synthesize a comprehensive, accurate, and engaging summary. "
                        "Do NOT just copy the bullet points. Add context where necessary. Reply in the same language as the user."
                    ),
                )
            ]
            if history:
                msgs.extend(history[-_HISTORY_WINDOW:])  # Context
            msgs.append(
                Message(
                    role="user", content=f"User Query: {prompt}\n\nSearch Results:\n{raw_result}"
                )
            )

            res = await self._llm.complete(msgs, tier="worker")
            content = str(res.get("content", res) if isinstance(res, dict) else res)

            return AgentResponse(
                content=content,
                steps=1,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )

        except Exception as e:
            logger.error("Fast web search error: %s", e)
            return None

    async def _handle_store(
        self,
        entity: str,
        agent_id: str,
    ) -> AgentResponse:
        """Store entity in memory.

        Phase 2: Uses LLM MemoryExtractor to split + type + score facts.
        Falls back to regex splitting if extractor unavailable.
        """
        try:
            # Phase 2: LLM-based extraction (preferred — no hard-code)
            facts = await self._extract_facts(entity)
            stored: list[str] = []

            for fact in facts:
                await self._tools.call(  # type: ignore[union-attr]
                    "memory_store",
                    {
                        "text": fact.text,
                        "agent_id": agent_id,
                        "importance": fact.importance,
                    },
                )
                stored.append(fact.text)
                logger.info(
                    "fast_path.store: type=%s importance=%d text=%r",
                    fact.fact_type,
                    fact.importance,
                    fact.text,
                )

            if len(stored) == 1:
                content = f"บันทึกเรียบร้อยครับ: {stored[0]} ✅"
            else:
                lines = "\n".join(f"  • {s}" for s in stored)
                content = f"บันทึกเรียบร้อย {len(stored)} รายการ ✅\n{lines}"

            return AgentResponse(
                content=content,
                steps=0,
                agent_id=agent_id,
                elapsed_ms=0,
            )
        except Exception as exc:
            logger.error("fast_path.store failed: %s", exc)
            return AgentResponse(
                content="ขออภัย ไม่สามารถบันทึกข้อมูลได้ในขณะนี้ครับ ❌",
                steps=0,
                agent_id=agent_id,
                elapsed_ms=0,
            )

    async def _extract_facts(self, text: str) -> list[object]:
        """Extract MemoryFacts via LLM extractor, falling back to regex."""
        try:
            from seahorse_ai.tools.memory_extractor import MemoryExtractor

            extractor = MemoryExtractor(llm_backend=self._llm)
            return await extractor.extract(text)
        except Exception as exc:
            logger.warning("fast_path: MemoryExtractor unavailable (%s) — using regex split", exc)
            from seahorse_ai.tools.memory_extractor import MemoryFact

            items = _split_entities(text)
            return [MemoryFact(text=item, importance=3) for item in items]

    async def _handle_query(
        self, entity: str, agent_id: str, history: list[Message] | None = None
    ) -> AgentResponse | None:
        """Search memory and synthesize an answer (Phase 4)."""
        if history:
            history = history[-_HISTORY_WINDOW:]
        try:
            from seahorse_ai.planner.memory_reasoner import MemoryReasoner

            reasoner = MemoryReasoner(llm_backend=self._llm, tools_registry=self._tools)
            return await reasoner.reason(query=entity, agent_id=agent_id, history=history)
        except Exception as exc:
            logger.error("fast_path.query failed: %s", exc)
            return None

    async def _handle_polars_analysis(
        self, prompt: str, history: list[Message] | None, start_t: float
    ) -> AgentResponse | None:
        """Directly fulfill data analysis requests via native Polars + Echarts."""
        try:
            from seahorse_ai.schemas import Message

            today = datetime.date.today().strftime("%Y-%m-%d")
            # Get schema context to avoid "muddling" column names
            schema = await self._tools.call("database_schema", {})

            extraction_prompt = f"""
            System Date: {today}
            Database Schema:
            {schema}
            
            Extract logic for Polars analysis and Echarts plotting.
            Return ONLY valid JSON.
            
            Extraction Logic:
            - Generate a SQL query that retrieves the raw data needed for the analysis.
            - Analyze: "Analyze sales over the last year" -> {{ "action": "POLARS_ANALYSIS", "entity": "sales", "timeframe": "last year" }}
            - If a time range is requested, calculate the correct date filter based on System Date.
            - DO NOT use small LIMIT clauses (e.g., LIMIT 10) if the user wants trend analysis or full reporting.
            - Ensure column names match the Schema provided exactly.
            
            JSON Fields:
            - "sql": SQL for database_query to get raw data
            - "aggregate_logic": List of {{'column': str, 'func': 'sum'|'mean'|'count'}}
            - "group_by": List of columns
            - "sort": List of columns
            - "chart_title": Title for the chart
            - "chart_type": 'bar' or 'line'
            
            User request: {prompt}
            """
            res = await self._llm.complete([Message(role="user", content=extraction_prompt)], tier="fast")
            if isinstance(res, dict):
                data = res.get("content", res)
                if isinstance(data, str):
                    data = _robust_json_load(data)
            else:
                data = _robust_json_load(str(res))

            sql = data.get("sql")
            if not sql:
                return None  # Fallback to ReAct if we can't build SQL

            # 2. Execute database_query
            raw_data = await self._tools.call("database_query", {"query": sql})
            
            # 3. Aggregation (Native Polars)
            agg_result = await self._tools.call("native_polars_aggregate", {
                "json_data": raw_data,
                "group_by": data.get("group_by", []),
                "aggregations": data.get("aggregate_logic", []),
                "sort_by": data.get("sort", [])
            })
            
            # 4. Visualization (Native Echarts)
            viz_result = await self._tools.call("native_echarts_chart", {
                "json_data": agg_result,
                "chart_type": data.get("chart_type", "bar"),
                "title": data.get("chart_title", "Analysis Result")
            })

            # 5. Final synthesis
            msgs = [
                Message(role="system", content="Synthesize a final report based on the analysis and chart provided.")
            ]
            if history:
                msgs.extend(history[-_HISTORY_WINDOW:])
            msgs.append(Message(role="user", content=f"Analysis: {agg_result}\nVisualization: {viz_result}"))
            final_res = await self._llm.complete(msgs, tier="worker")
            content = str(final_res.get("content", final_res) if isinstance(final_res, dict) else final_res)

            return AgentResponse(
                content=f"{content}\n\n{viz_result}",
                steps=3,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )

        except Exception as e:
            logger.error(f"Fast Polars analysis error: {e}")
            return None

    async def _handle_football_intel(
        self, prompt: str, history: list[Message] | None, start_t: float
    ) -> AgentResponse | None:
        """Directly fulfill football intelligence requests via optimized tool calls.

        All mathematical analysis (probabilities, Poisson, edge, Kelly) is
        pre-computed in Python.  The LLM only handles presentation/synthesis —
        it is never asked to compute numbers.
        """
        try:
            today = datetime.date.today().strftime("%Y-%m-%d")

            extraction_prompt = f"""
            System Date: {today}
            Extract football match details for API search.
            Return ONLY valid JSON.

            IMPORTANT: For "teamname", use the simplest possible common name (e.g., 'Arsenal').
            If the user asks for "today", "now", or general "Value" without a team, set "teamname" to "ALL".

            Context Extraction:
            - If one or more leagues or countries are mentioned (e.g. "Premier League", "La Liga", "England"), extract them into a list.

            JSON Fields:
            - "teamname": Team name or "ALL"
            - "leagues": List of league names (e.g., ['Premier League', 'La Liga']) or null
            - "countries": List of country names or null
            - "date": YYYY-MM-DD
            - "request_type": 'odds' | 'intel' | 'h2h' | 'value'
            - "is_ranking": boolean (true if user wants a comparison, top matches, highest-to-lowest, or list)

            STRICT RULES:
            - If the user mentions "Serie A", "Serie B", or "Premier League", check if they also mentioned a country (Italy, Brazil, England). If not, default to the most famous one but keep "countries" as null or ALL unless sure.
            - ALWAYS try to extract a list of "countries" if mentioned.

            User request: {prompt}
            """
            res = await self._llm.complete([Message(role="user", content=extraction_prompt)], tier="fast")
            data = _robust_json_load(str(res.get("content", res) if isinstance(res, dict) else res))

            team = data.get("teamname")
            leagues_req = data.get("leagues") or ([data.get("leaguename")] if data.get("leaguename") else [])
            countries_req = data.get("countries") or ([data.get("country")] if data.get("country") else [])
            date = data.get("date", today)
            req_type = data.get("request_type", "value")
            is_ranking = data.get("is_ranking", False)

            if not team:
                return None

            hint_league = leagues_req[0] if leagues_req else None
            fixtures_json = await self._tools.call("searchfixture", {
                "teamname": team,
                "date": date,
                "leaguename": hint_league,
            })

            if not (isinstance(fixtures_json, str) and (fixtures_json.startswith("[") or fixtures_json.startswith("{"))):
                return AgentResponse(content=fixtures_json, steps=1, elapsed_ms=int((time.perf_counter() - start_t) * 1000))

            fixtures = json.loads(fixtures_json)

            if not fixtures:
                league_check = await self._tools.call("searchleague", {"name": hint_league or team})
                if "No leagues found" in league_check:
                    return AgentResponse(
                        content=f"ไม่พบข้อมูลลีกหรือทีมที่ชื่อ '{hint_league or team}' ครับ รบกวนตรวจสอบชื่ออีกครั้ง",
                        steps=1,
                        elapsed_ms=int((time.perf_counter() - start_t) * 1000),
                    )

                msg = f"ไม่พบข้อมูลการแข่งขันของ {team}"
                if leagues_req:
                    msg += f" ใน {', '.join(leagues_req)}"
                msg += f" ในวันที่ {date} ครับ (แต่อาจจะมีในวันอื่น)"
                return AgentResponse(content=msg, steps=1, elapsed_ms=int((time.perf_counter() - start_t) * 1000))

            # ── Target Selection ─────────────────────────────────────────
            targets = _select_targets(fixtures, leagues_req, countries_req, is_ranking)

            from seahorse_ai.tools.football_stats import getsportkey

            league_for_odds = leagues_req[0] if leagues_req else (targets[0].get("league", "") if targets else "")
            sport_key = getsportkey(league_for_odds) if league_for_odds else None

            # ── Parallel Deep Analysis ───────────────────────────────────
            async def analyze_target(target: dict) -> dict:
                fid = target["fixture_id"]
                h_id = target.get("home_team_id")
                a_id = target.get("away_team_id")
                
                tasks = []
                if req_type in ("intel", "value"):
                    tasks.append(self._tools.call("getmatchintel", {"fixtureid": fid}))
                if req_type in ("odds", "value"):
                    # For Football-Data.org, we prioritize comparemarketodds for bulk
                    # but we keep fetchliveodds for compatibility
                    tasks.append(self._tools.call("fetchliveodds", {"fixtureid": fid}))
                
                # Fetch statistical backup for Poisson
                if h_id:
                    tasks.append(self._tools.call("getteamxg", {"teamid": h_id}))
                if a_id:
                    tasks.append(self._tools.call("getteamxg", {"teamid": a_id}))

                results = await asyncio.gather(*tasks)

                from seahorse_ai.analysis.football_eval import extract_and_persist, parse_football_data

                parsed_stats = parse_football_data(target, results)
                asyncio.create_task(extract_and_persist(target, results))
                return parsed_stats

            analysis_tasks = [analyze_target(t) for t in targets]
            if sport_key and is_ranking:
                analysis_tasks.append(self._tools.call("comparemarketodds", {"sportkey": sport_key}))

            all_results = await asyncio.gather(*analysis_tasks)
 
            match_stats: list[dict] = all_results[:len(targets)]
            bulk_odds_text = all_results[len(targets)] if len(all_results) > len(targets) else ""
            
            # ── Inject Bulk Odds into Individual Stats ───────────────────
            if bulk_odds_text and isinstance(bulk_odds_text, str):
                import re
                for stats in match_stats:
                    m_name = stats.get("match_name", "")
                    # Extract MaxOdds(1:X X:Y 2:Z) from bulk text
                    # Example: "Man Utd vs Aston Villa: MaxOdds(1:1.75 X:4.25 2:5.0)"
                    pattern = rf"{re.escape(m_name)}: MaxOdds\(1:([\d.]+) X:([\d.]+) 2:([\d.]+)\)"
                    match = re.search(pattern, bulk_odds_text)
                    if match:
                        stats["odds_home"] = float(match.group(1))
                        stats["odds_draw"] = float(match.group(2))
                        stats["odds_away"] = float(match.group(3))
                        # Trigger re-calculation of edge with new odds
                        from seahorse_ai.analysis.football_eval import parse_football_data
                        # Re-run parse (it's safe as it's deterministic) to update best_edge
                        # We pass a fake result that will be parsed as BestOdds
                        odds_str = f"BestOdds 1:{stats['odds_home']} X:{stats['odds_draw']} 2:{stats['odds_away']}"
                        stats.update(parse_football_data(stats, [odds_str]))

            # ── Pre-format analysis in Python (LLM only does presentation) ──
            report_blocks: list[str] = []
            for stats in match_stats:
                report_blocks.append(_format_match_report(stats))

            pre_computed = "\n\n".join(report_blocks)

            synthesis_prompt = f"""
You are a football analyst. The user asked: "{prompt}"
Today: {today}. {len(targets)} match(es) analyzed.

ALL numbers below are PRE-COMPUTED BY PYTHON. Do NOT recalculate or invent numbers.
Your job is ONLY to present this data in a clear, professional report.

--- PRE-COMPUTED DATA ---
{pre_computed}
"""
            if bulk_odds_text:
                synthesis_prompt += f"\n--- MARKET COMPARISON ---\n{bulk_odds_text}\n"

            synthesis_prompt += """
--- REPORT RULES ---
1. USE the exact numbers above. Copy them, do not modify.
2. If a value is "N/A" or 0.0, say "Unavailable".
3. If best_edge > 5%, highlight as HIGH VALUE.  If negative, say SKIP.
4. Use tables for multi-match summaries. Rank by edge (highest first).
5. Reply in the same language the user used (Thai/English).
6. Include the Poisson most likely score and Over/Under 2.5 analysis.
"""
            final_res = await self._llm.complete([Message(role="user", content=synthesis_prompt)], tier="worker")
            content = str(final_res.get("content", final_res) if isinstance(final_res, dict) else final_res)

            return AgentResponse(
                content=content,
                steps=len(targets) * 2 + 1,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )

        except Exception as e:
            logger.error("Fast football intel error: %s", e)
            return None


# ── Helper functions ───────────────────────────────────────────────────────────

_SPLIT_DELIMITERS = re.compile(r"[,،;]\s*|\sและ\s|\sand\s", re.IGNORECASE)


def _split_entities(entity: str) -> list[str]:
    """Split comma/และ/and-separated items into individual facts.

    'Packet B ราคา 5,000 , Packet C ราคา 7,500'
    → ['Packet B ราคา 5,000', 'Packet C ราคา 7,500']

    Handles price commas (1,200) by only splitting on comma-space.
    """
    # Only split on ", " (comma + space) to avoid splitting "1,200"
    parts = re.split(r",\s+|\sและ\s|\sand\s", entity, flags=re.IGNORECASE)
    items = [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]
    return items if items else [entity]


def _robust_json_load(text: str) -> dict[str, Any]:
    """Extract and parse JSON from text, handling markdown fences or preamble."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _select_targets(
    fixtures: list[dict],
    leagues_req: list[str],
    countries_req: list[str],
    is_ranking: bool,
) -> list[dict]:
    """Filter and rank fixtures, returning up to 5 (ranking) or 1 (specific)."""
    youth_terms = ("U18", "U21", "U23", "Reserve", "Women", "Youth")
    is_youth_req = any(
        ut.lower() in (lreq.lower() for lreq in leagues_req) for ut in youth_terms
    )

    if leagues_req and len(leagues_req) == 1 and "," in leagues_req[0]:
        leagues_req[:] = [lreq.strip() for lreq in leagues_req[0].split(",")]

    filtered: list[dict] = []
    for f in fixtures:
        l_name = f.get("league", "").lower()
        if leagues_req and not any(ln.lower() in l_name for ln in leagues_req):
            continue
        if not is_youth_req and any(ut.lower() in l_name for ut in youth_terms):
            continue
        filtered.append(f)

    if not filtered:
        filtered = fixtures

    major = ("premier league", "la liga", "serie a", "bundesliga", "ligue 1",
             "uefa champions league", "thai league 1")

    def score_match(f: dict) -> int:
        s = 0
        l_name = f.get("league", "").lower()
        c_name = f.get("country", "").lower()
        if leagues_req and any(ln.lower() == l_name for ln in leagues_req):
            s += 100
        elif leagues_req and any(ln.lower() in l_name for ln in leagues_req):
            s += 50
        if countries_req and any(cn.lower() in c_name for cn in countries_req):
            s += 40
        if any(ml in l_name for ml in major):
            s += 30
        return s

    filtered.sort(key=score_match, reverse=True)
    return filtered[: 5 if is_ranking else 1]


def _format_match_report(stats: dict) -> str:
    """Format pre-computed stats into a text block for the LLM to present."""
    lines = [
        f"### {stats.get('match_name', 'Unknown')} ({stats.get('league_name', '')} - {stats.get('country', '')})",
        "",
        f"API Prob: Home {stats.get('prob_h', 0):.1%}  Draw {stats.get('prob_d', 0):.1%}  Away {stats.get('prob_a', 0):.1%}",
        f"xG (avg last 5): Home {stats.get('h_xg', 'N/A')}  Away {stats.get('a_xg', 'N/A')}",
    ]

    if stats.get("poisson_h", 0) > 0:
        lines.append(
            f"Poisson Prob: Home {stats['poisson_h']:.1%}  Draw {stats['poisson_d']:.1%}  Away {stats['poisson_a']:.1%}"
        )
        lines.append(
            f"Most Likely Score: {stats.get('most_likely_score', 'N/A')} (prob {stats.get('most_likely_score_prob', 0):.1%})"
        )
        lines.append(
            f"Over 2.5: {stats.get('poisson_over25', 0):.1%}  Under 2.5: {stats.get('poisson_under25', 0):.1%}"
        )

    lines.append("")
    lines.append("Market Odds (best across bookmakers):")
    lines.append(
        f"  Home: {stats.get('odds_home', 0):.2f} ({stats.get('bk_home', '')})"
        f"  Draw: {stats.get('odds_draw', 0):.2f} ({stats.get('bk_draw', '')})"
        f"  Away: {stats.get('odds_away', 0):.2f} ({stats.get('bk_away', '')})"
    )

    if stats.get("ou_over25_odds", 0) > 0:
        lines.append(
            f"  Over 2.5: {stats['ou_over25_odds']:.2f}  Under 2.5: {stats.get('ou_under25_odds', 0):.2f}"
        )

    lines.append("")
    lines.append("Edge Analysis (all 3 outcomes):")
    lines.append(
        f"  Home edge: {stats.get('edge_home', 0):+.2%}"
        f"  Draw edge: {stats.get('edge_draw', 0):+.2%}"
        f"  Away edge: {stats.get('edge_away', 0):+.2%}"
    )
    lines.append(
        f"  >>> BEST VALUE: {stats.get('best_side', 'N/A')}"
        f" @ {stats.get('best_odds', 0):.2f}"
        f"  Edge: {stats.get('best_edge', 0):+.2%}"
        f"  Kelly stake: {stats.get('best_stake', 0):.2%} of bankroll"
    )

    if stats.get("ou_edge_over25", 0) != 0 or stats.get("ou_edge_under25", 0) != 0:
        lines.append(
            f"  Over 2.5 edge: {stats.get('ou_edge_over25', 0):+.2%}"
            f"  Under 2.5 edge: {stats.get('ou_edge_under25', 0):+.2%}"
        )

    lines.append("")
    lines.append(f"H2H matches: {stats.get('h2h_count', 0)}  Advice: {stats.get('advice', 'N/A')}")

    comparison = stats.get("comparison", {})
    if comparison:
        lines.append("Form comparison:")
        for key, val in comparison.items():
            if isinstance(val, dict):
                lines.append(f"  {key}: Home {val.get('home', 'N/A')}  Away {val.get('away', 'N/A')}")

    return "\n".join(lines)
