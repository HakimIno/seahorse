from __future__ import annotations
import datetime
import time
import json
import logging
import re
import asyncio
from typing import Any, TYPE_CHECKING
from seahorse_ai.planner.handlers.base import BaseFastHandler
from seahorse_ai.schemas import Message, AgentResponse
from seahorse_ai.planner.fast_utils import robust_json_load

if TYPE_CHECKING:
    from seahorse_ai.router import ModelRouter
    from seahorse_ai.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

class FootballHandler(BaseFastHandler):
    """Handles football intelligence, odds, and match analysis."""

    async def handle(self, prompt: str, history: list[Message] | None, start_t: float, **kwargs: Any) -> AgentResponse | None:
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
            - "leagues": List of league names or null
            - "countries": List of country names or null
            - "date": YYYY-MM-DD
            - "request_type": 'odds' | 'intel' | 'h2h' | 'value'
            - "is_ranking": boolean
            User request: {prompt}
            """
            res = await self._llm.complete([Message(role="user", content=extraction_prompt)], tier="fast")
            data = robust_json_load(str(res.get("content", res) if isinstance(res, dict) else res))

            team = data.get("teamname")
            if not team: return None

            leagues_req = data.get("leagues") or []
            countries_req = data.get("countries") or []
            date = data.get("date", today)
            req_type = data.get("request_type", "value")
            is_ranking = data.get("is_ranking", False)

            hint_league = leagues_req[0] if leagues_req else None
            fixtures_json = await self._tools.call("searchfixture", {
                "teamname": team, "date": date, "leaguename": hint_league
            })
            if not (isinstance(fixtures_json, str) and (fixtures_json.startswith("[") or fixtures_json.startswith("{"))):
                return AgentResponse(content=fixtures_json, steps=1, elapsed_ms=int((time.perf_counter() - start_t) * 1000))

            fixtures = json.loads(fixtures_json)
            if not fixtures:
                return AgentResponse(content=f"No matches found for {team} on {date}.", steps=1)

            targets = self._select_targets(fixtures, leagues_req, countries_req, is_ranking)
            
            from seahorse_ai.tools.football_stats import getsportkey
            league_for_odds = leagues_req[0] if leagues_req else (targets[0].get("league", "") if targets else "")
            sport_key = getsportkey(league_for_odds) if league_for_odds else None

            analysis_tasks = [self._analyze_target(t, req_type) for t in targets]
            if sport_key and is_ranking:
                analysis_tasks.append(self._tools.call("comparemarketodds", {"sportkey": sport_key}))

            all_results = await asyncio.gather(*analysis_tasks)
            match_stats: list[dict] = all_results[:len(targets)]
            bulk_odds_text = all_results[len(targets)] if len(all_results) > len(targets) else ""
            
            # Inject Bulk Odds
            if bulk_odds_text and isinstance(bulk_odds_text, str):
                for stats in match_stats:
                    m_name = stats.get("match_name", "")
                    pattern = rf"{re.escape(m_name)}: MaxOdds\(1:([\d.]+) X:([\d.]+) 2:([\d.]+)\)"
                    match = re.search(pattern, bulk_odds_text)
                    if match:
                        stats["odds_home"] = float(match.group(1))
                        stats["odds_draw"] = float(match.group(2))
                        stats["odds_away"] = float(match.group(3))
                        from seahorse_ai.analysis.football_eval import parse_football_data
                        odds_str = f"BestOdds 1:{stats['odds_home']} X:{stats['odds_draw']} 2:{stats['odds_away']}"
                        stats.update(parse_football_data(stats, [odds_str]))

            report_blocks = [self._format_match_report(s) for s in match_stats]
            pre_computed = "\n\n".join(report_blocks)

            synthesis_prompt = f"Football Report:\n{pre_computed}"
            if bulk_odds_text: synthesis_prompt += f"\n\nMarket Comparison:\n{bulk_odds_text}"
            
            final_res = await self._llm.complete([Message(role="user", content=synthesis_prompt)], tier="worker")
            content = str(final_res.get("content", final_res) if isinstance(final_res, dict) else final_res)

            return AgentResponse(content=content, steps=len(targets)*2+1, elapsed_ms=int((time.perf_counter() - start_t) * 1000))

        except Exception as e:
            logger.error(f"FootballHandler error: {e}")
            return None

    def _select_targets(self, fixtures, leagues_req, countries_req, is_ranking):
        youth_terms = ("U18", "U21", "U23", "Reserve", "Women", "Youth")
        is_youth_req = any(ut.lower() in (lreq.lower() for lreq in leagues_req) for ut in youth_terms)
        
        filtered = []
        for f in fixtures:
            l_name = f.get("league", "").lower()
            if leagues_req and not any(ln.lower() in l_name for ln in leagues_req): continue
            if not is_youth_req and any(ut.lower() in l_name for ut in youth_terms): continue
            filtered.append(f)
        if not filtered: filtered = fixtures

        major = ("premier league", "la liga", "serie a", "bundesliga", "ligue 1", "uefa champions league", "thai league 1")
        def score_match(f: dict) -> int:
            s = 0
            l_name = f.get("league", "").lower()
            c_name = f.get("country", "").lower()
            if leagues_req and any(ln.lower() == l_name for ln in leagues_req): s += 100
            if countries_req and any(cn.lower() in c_name for cn in countries_req): s += 40
            if any(ml in l_name for ml in major): s += 30
            return s

        filtered.sort(key=score_match, reverse=True)
        return filtered[: 5 if is_ranking else 1]

    async def _analyze_target(self, target: dict, req_type: str) -> dict:
        fid = target["fixture_id"]
        h_id = target.get("home_team_id")
        a_id = target.get("away_team_id")
        tasks = []
        if req_type in ("intel", "value"): tasks.append(self._tools.call("getmatchintel", {"fixtureid": fid}))
        if req_type in ("odds", "value"): tasks.append(self._tools.call("fetchliveodds", {"fixtureid": fid}))
        if h_id: tasks.append(self._tools.call("getteamxg", {"teamid": h_id}))
        if a_id: tasks.append(self._tools.call("getteamxg", {"teamid": a_id}))
        
        results = await asyncio.gather(*tasks)
        from seahorse_ai.analysis.football_eval import extract_and_persist, parse_football_data
        parsed_stats = parse_football_data(target, results)
        asyncio.create_task(extract_and_persist(target, results))
        return parsed_stats

    def _format_match_report(self, stats: dict) -> str:
        lines = [f"### {stats.get('match_name', 'Unknown')} ({stats.get('league_name', '')})",
                 f"API Prob: H {stats.get('prob_h', 0):.1%} D {stats.get('prob_d', 0):.1%} A {stats.get('prob_a', 0):.1%}",
                 f"xG Avg: H {stats.get('h_xg', 'N/A')} A {stats.get('a_xg', 'N/A')}"]
        if stats.get("poisson_h", 0) > 0:
            lines.append(f"Poisson: H {stats['poisson_h']:.1%} D {stats['poisson_d']:.1%} A {stats['poisson_a']:.1%}")
        lines.append(f"Best Value: {stats.get('best_side', 'N/A')} @ {stats.get('best_odds', 0):.2f} Edge: {stats.get('best_edge', 0):+.2%}")
        return "\n".join(lines)
