import logging
import math
import os
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

PG_URI = os.environ.get("FOOTBALL_PG_URI", os.environ.get("SEAHORSE_PG_URI"))

_pool: Any | None = None


async def _get_pool() -> Any | None:
    global _pool
    if _pool is None and PG_URI:
        _pool = await asyncpg.create_pool(PG_URI, min_size=1, max_size=5)
    return _pool

async def init_eval_db() -> None:
    """Initialize or migrate the football_predictions table."""
    pool = await _get_pool()
    if not pool:
        logger.error("FootballEval: No PG_URI configured. DB initialization skipped.")
        return

    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS football_predictions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    fixture_id INTEGER NOT NULL,
                    match_name TEXT NOT NULL,
                    league_id INTEGER,
                    league_name TEXT,
                    country TEXT,
                    predicted_prob_h FLOAT,
                    predicted_prob_d FLOAT,
                    predicted_prob_a FLOAT,
                    market_odds FLOAT,
                    market_side TEXT,
                    calculated_edge FLOAT,
                    recommended_stake FLOAT,
                    poisson_prob_h FLOAT,
                    poisson_prob_d FLOAT,
                    poisson_prob_a FLOAT,
                    poisson_over25 FLOAT,
                    most_likely_score TEXT,
                    status TEXT DEFAULT 'PENDING',
                    actual_score TEXT,
                    actual_outcome TEXT,
                    profit_loss FLOAT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_fb_fixture_id ON football_predictions(fixture_id);
                CREATE INDEX IF NOT EXISTS idx_fb_status ON football_predictions(status);
            """)

            new_columns = [
                ("poisson_prob_h", "FLOAT"),
                ("poisson_prob_d", "FLOAT"),
                ("poisson_prob_a", "FLOAT"),
                ("poisson_over25", "FLOAT"),
                ("most_likely_score", "TEXT"),
            ]
            for col_name, col_type in new_columns:
                try:
                    await conn.execute(
                        f"ALTER TABLE football_predictions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    )
                except Exception:
                    pass

        logger.info("FootballEval: Database initialized/migrated successfully.")
    except Exception as e:
        logger.error("FootballEval: Failed to initialize DB: %s", e)

async def persist_prediction(data: dict[str, Any]) -> None:
    """Save a new prediction record to the database."""
    pool = await _get_pool()
    if not pool:
        return

    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO football_predictions (
                    fixture_id, match_name, league_id, league_name, country,
                    predicted_prob_h, predicted_prob_d, predicted_prob_a,
                    market_odds, market_side, calculated_edge, recommended_stake,
                    poisson_prob_h, poisson_prob_d, poisson_prob_a,
                    poisson_over25, most_likely_score
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            """,
            data.get("fixture_id"),
            data.get("match_name"),
            data.get("league_id"),
            data.get("league_name"),
            data.get("country"),
            data.get("prob_h"),
            data.get("prob_d"),
            data.get("prob_a"),
            data.get("best_odds"),
            data.get("best_side"),
            data.get("best_edge"),
            data.get("best_stake"),
            data.get("poisson_h"),
            data.get("poisson_d"),
            data.get("poisson_a"),
            data.get("poisson_over25"),
            data.get("most_likely_score"),
            )
        logger.info("FootballEval: Persisted prediction for %s (ID: %s)", data.get("match_name"), data.get("fixture_id"))
    except Exception as e:
        logger.error("FootballEval: Failed to persist prediction: %s", e)

def _poisson_prob(k: int, lam: float) -> float:
    """Single Poisson probability P(X=k) given mean lam."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)


def compute_poisson_prediction(
    home_xg: float, away_xg: float, max_goals: int = 7
) -> dict[str, Any]:
    """Full Poisson-based prediction from xG averages.

    Returns probabilities for Home/Draw/Away, Over/Under 2.5,
    score matrix, and the most likely scoreline.
    """
    home_win = 0.0
    away_win = 0.0
    draw = 0.0
    over25 = 0.0
    best_score = (0, 0)
    best_score_prob = 0.0

    for h in range(max_goals):
        for a in range(max_goals):
            p = _poisson_prob(h, home_xg) * _poisson_prob(a, away_xg)
            if h > a:
                home_win += p
            elif a > h:
                away_win += p
            else:
                draw += p
            if h + a > 2:
                over25 += p
            if p > best_score_prob:
                best_score_prob = p
                best_score = (h, a)

    return {
        "poisson_h": round(home_win, 4),
        "poisson_d": round(draw, 4),
        "poisson_a": round(away_win, 4),
        "poisson_over25": round(over25, 4),
        "poisson_under25": round(1.0 - over25, 4),
        "most_likely_score": f"{best_score[0]}-{best_score[1]}",
        "most_likely_score_prob": round(best_score_prob, 4),
    }


def _calc_edge_and_kelly(
    prob: float, odds: float, kelly_fraction: float = 0.5
) -> tuple[float, float]:
    """Return (edge, recommended_stake_fraction) for a single outcome."""
    if prob <= 0 or odds <= 1:
        return 0.0, 0.0
    edge = (prob * odds) - 1.0
    b = odds - 1.0
    kelly = (b * prob - (1.0 - prob)) / b if b > 0 else 0.0
    stake = max(0.0, kelly * kelly_fraction)
    return round(edge, 4), round(stake, 4)


def _extract_best_odds(bookmakers: list[dict]) -> dict[str, float]:
    """Find the best (highest) odds across ALL bookmakers for each outcome."""
    best: dict[str, float] = {"Home": 0.0, "Draw": 0.0, "Away": 0.0}
    best_bk: dict[str, str] = {"Home": "", "Draw": "", "Away": ""}

    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            if bet.get("name") == "Match Winner":
                for val in bet.get("values", []):
                    side = val.get("value", "")
                    try:
                        price = float(val.get("odd", 0))
                    except (ValueError, TypeError):
                        continue
                    if side in best and price > best[side]:
                        best[side] = price
                        best_bk[side] = bm_name

    return {
        "odds_home": best["Home"],
        "odds_draw": best["Draw"],
        "odds_away": best["Away"],
        "bk_home": best_bk["Home"],
        "bk_draw": best_bk["Draw"],
        "bk_away": best_bk["Away"],
    }


def _extract_ou_odds(bookmakers: list[dict]) -> dict[str, float]:
    """Extract Over/Under 2.5 odds from bookmakers."""
    best_over = 0.0
    best_under = 0.0
    for bm in bookmakers:
        for bet in bm.get("bets", []):
            if "Over/Under" in bet.get("name", "") or "Goals" in bet.get("name", ""):
                for val in bet.get("values", []):
                    v = str(val.get("value", ""))
                    try:
                        price = float(val.get("odd", 0))
                    except (ValueError, TypeError):
                        continue
                    if "Over" in v and "2.5" in v and price > best_over:
                        best_over = price
                    elif "Under" in v and "2.5" in v and price > best_under:
                        best_under = price
    return {"ou_over25": best_over, "ou_under25": best_under}


def parse_football_data(target: dict, results: list[str]) -> dict[str, Any]:
    """Parse raw tool results into a structured dictionary with verified stats.

    Evaluates ALL 3 outcomes (Home/Draw/Away) to find the best edge.
    Integrates Poisson model when xG data is available.
    Adds Over/Under 2.5 analysis.
    """
    import json

    data: dict[str, Any] = {
        "fixture_id": target.get("fixture_id"),
        "match_name": target.get("match") or target.get("match_name"),
        "league_id": target.get("league_id"),
        "league_name": target.get("league") or target.get("league_name"),
        "country": target.get("country"),
        "prob_h": _safe_float(target.get("prob_h", 0.0)),
        "prob_d": _safe_float(target.get("prob_d", 0.0)),
        "prob_a": _safe_float(target.get("prob_a", 0.0)),
        "odds_home": _safe_float(target.get("odds_home", 0.0)),
        "odds_draw": _safe_float(target.get("odds_draw", 0.0)),
        "odds_away": _safe_float(target.get("odds_away", 0.0)),
        "bk_home": target.get("bk_home", ""),
        "bk_draw": target.get("bk_draw", ""),
        "bk_away": target.get("bk_away", ""),
        "edge_home": 0.0, "edge_draw": 0.0, "edge_away": 0.0,
        "best_side": target.get("best_side", "Home"),
        "best_odds": _safe_float(target.get("best_odds", 0.0)),
        "best_edge": _safe_float(target.get("best_edge", 0.0)),
        "best_stake": _safe_float(target.get("best_stake", 0.0)),
        "h_xg": target.get("h_xg", "N/A"),
        "a_xg": target.get("a_xg", "N/A"),
        "h2h_count": target.get("h2h_count", 0),
        "advice": target.get("advice", "N/A"),
        "comparison": target.get("comparison", {}),
        # Poisson-based
        "poisson_h": _safe_float(target.get("poisson_h", 0.0)),
        "poisson_d": _safe_float(target.get("poisson_d", 0.0)),
        "poisson_a": _safe_float(target.get("poisson_a", 0.0)),
        "poisson_over25": _safe_float(target.get("poisson_over25", 0.0)),
        "poisson_under25": _safe_float(target.get("poisson_under25", 0.0)),
        "most_likely_score": target.get("most_likely_score", "N/A"),
        "most_likely_score_prob": _safe_float(target.get("most_likely_score_prob", 0.0)),
        # Over/Under market
        "ou_over25_odds": _safe_float(target.get("ou_over25_odds", 0.0)),
        "ou_under25_odds": _safe_float(target.get("ou_under25_odds", 0.0)),
        "ou_edge_over25": _safe_float(target.get("ou_edge_over25", 0.0)),
        "ou_edge_under25": _safe_float(target.get("ou_edge_under25", 0.0)),
    }

    for r in results:
        try:
            parsed = json.loads(r)
        except (json.JSONDecodeError, TypeError):
            if isinstance(r, str) and (r.startswith("Market(") or r.startswith("BestOdds ")):
                _parse_condensed_market(r, data)
            continue

        # API-Football predictions (Legacy/Deprecating)
        if isinstance(parsed, dict) and "predictions" in parsed:
            _ingest_predictions(parsed, data)
        # Football-Data.org Match object
        elif isinstance(parsed, dict) and "homeTeam" in parsed and "awayTeam" in parsed:
            _ingest_fd_match(parsed, data)
        # Odds data
        elif isinstance(parsed, dict) and (
            "bookmakers" in parsed
            or ("response" in parsed and parsed.get("response"))
        ):
            _ingest_odds(parsed, data)
        # Numeric xG/Average (handled as float after json.loads)
        elif isinstance(parsed, (int, float)):
            if data["h_xg"] == "N/A" or data["h_xg"] == 0.0:
                data["h_xg"] = parsed
            else:
                data["a_xg"] = parsed

    # ── Internal Poisson prediction ──────────────────────────────────────
    # We now calculation xG from FD match history if available,
    # or use the h_xg / a_xg fields if populated by tools.
    h_xg = _safe_float(data["h_xg"])
    a_xg = _safe_float(data["a_xg"])
    if h_xg > 0 and a_xg > 0:
        poisson = compute_poisson_prediction(h_xg, a_xg)
        data.update(poisson)

    # ── Evaluate edge for ALL 3 outcomes ──────────────────────────────────
    # Prefer internal poisson if available (vital for Football-Data.org)
    prob_source = "poisson" if data["poisson_h"] > 0 else "api"
    probs = {
        "Home": data[f"{prob_source}_h"] if prob_source == "poisson" else data["prob_h"],
        "Draw": data[f"{prob_source}_d"] if prob_source == "poisson" else data["prob_d"],
        "Away": data[f"{prob_source}_a"] if prob_source == "poisson" else data["prob_a"],
    }
    odds_map = {
        "Home": data["odds_home"],
        "Draw": data["odds_draw"],
        "Away": data["odds_away"],
    }

    best_side, best_edge, best_odds, best_stake = "Home", -999.0, 0.0, 0.0
    for side in ("Home", "Draw", "Away"):
        edge, stake = _calc_edge_and_kelly(probs[side], odds_map[side])
        data[f"edge_{side.lower()}"] = edge
        if edge > best_edge and odds_map[side] > 0:
            best_side, best_edge, best_odds, best_stake = side, edge, odds_map[side], stake

    data["best_side"] = best_side
    data["best_edge"] = best_edge
    data["best_odds"] = best_odds
    data["best_stake"] = best_stake

    # ── Over/Under 2.5 edge ──────────────────────────────────────────────
    if data["poisson_over25"] > 0 and data["ou_over25_odds"] > 0:
        data["ou_edge_over25"], _ = _calc_edge_and_kelly(
            data["poisson_over25"], data["ou_over25_odds"]
        )
    if data["poisson_under25"] > 0 and data["ou_under25_odds"] > 0:
        data["ou_edge_under25"], _ = _calc_edge_and_kelly(
            data["poisson_under25"], data["ou_under25_odds"]
        )

    return data


def _ingest_fd_match(parsed: dict, data: dict) -> None:
    """Extract data from a Football-Data.org match object."""
    # Football-Data.org doesn't provide win probs directly, we just map IDs/names
    data["fixture_id"] = parsed.get("id", data["fixture_id"])
    data["match_name"] = f"{parsed.get('homeTeam', {}).get('name')} vs {parsed.get('awayTeam', {}).get('name')}"
    data["league_name"] = parsed.get("competition", {}).get("name", data["league_name"])
    
    # xG is not in FD, but we might have fetched it separately or from hist
    score = parsed.get("score", {})
    if score.get("fullTime", {}).get("home") is not None:
         # This is a finished match, usually for result collection
         pass

def _ingest_predictions(parsed: dict, data: dict) -> None:
    """Extract API-Football prediction data."""
    preds = parsed.get("predictions", {})
    pct = preds.get("percent", {})
    data["prob_h"] = _safe_float(str(pct.get("home", "0")).replace("%", "")) / 100
    data["prob_d"] = _safe_float(str(pct.get("draw", "0")).replace("%", "")) / 100
    data["prob_a"] = _safe_float(str(pct.get("away", "0")).replace("%", "")) / 100
    data["h2h_count"] = len(parsed.get("h2h", []))
    data["advice"] = preds.get("advice", "N/A")
    data["comparison"] = parsed.get("comparison", {})

    teams = parsed.get("teams", {})
    data["h_xg"] = (
        teams.get("home", {}).get("last_5", {})
        .get("goals", {}).get("for", {}).get("average", "N/A")
    )
    data["a_xg"] = (
        teams.get("away", {}).get("last_5", {})
        .get("goals", {}).get("for", {}).get("average", "N/A")
    )


def _ingest_odds(parsed: dict, data: dict) -> None:
    """Extract odds from API-Football response — best across ALL bookmakers."""
    odds_resp = parsed.get("response", [parsed])
    if isinstance(odds_resp, list) and odds_resp:
        odds_resp = odds_resp[0]
    bookmakers = odds_resp.get("bookmakers", []) if isinstance(odds_resp, dict) else []

    best = _extract_best_odds(bookmakers)
    data.update(best)

    ou = _extract_ou_odds(bookmakers)
    data["ou_over25_odds"] = ou["ou_over25"]
    data["ou_under25_odds"] = ou["ou_under25"]


def _parse_condensed_market(text: str, data: dict) -> None:
    """Parse the condensed 'Market(BkName): 1:X X:Y 2:Z' format."""
    import re
    m = re.search(r"1:([\d.]+)\s+X:([\d.]+)\s+2:([\d.]+)", text)
    if m:
        data["odds_home"] = max(data["odds_home"], _safe_float(m.group(1)))
        data["odds_draw"] = max(data["odds_draw"], _safe_float(m.group(2)))
        data["odds_away"] = max(data["odds_away"], _safe_float(m.group(3)))


def _safe_float(val: Any) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

async def extract_and_persist(target: dict, results: list[str]):
    """Helper to parse raw tool results and call persist_prediction."""
    data = parse_football_data(target, results)
    await persist_prediction(data)

async def resolve_pending_predictions() -> None:
    """Fetch results for pending matches and update their outcomes."""
    import json

    from seahorse_ai.tools.football.football_stats import fetchlivematch

    pool = await _get_pool()
    if not pool:
        return

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, fixture_id, market_side, market_odds, recommended_stake
                FROM football_predictions
                WHERE status = 'PENDING'
                AND created_at < NOW() - INTERVAL '3 hours'
            """)

            for row in rows:
                try:
                    res_raw = fetchlivematch(row["fixture_id"])
                    if not res_raw or not res_raw.startswith("{"):
                        logger.warning("FootballEval: Auto-voiding legacy fixture %s", row["fixture_id"])
                        await conn.execute("UPDATE football_predictions SET status = 'VOID', updated_at = NOW() WHERE id = $1", row["id"])
                        continue
                        
                    res = json.loads(res_raw)
                    h_goals, a_goals, outcome = None, None, None
                    status_str = None

                    # Football-Data.org schema
                    if "status" in res and isinstance(res["status"], str):
                        status_str = res["status"]
                        if status_str == "FINISHED":
                             score = res.get("score", {})
                             full_time = score.get("fullTime", {})
                             h_goals = full_time.get("match_home", full_time.get("home", 0))
                             a_goals = full_time.get("match_away", full_time.get("away", 0))
                        elif status_str in ("CANCELLED", "POSTPONED"):
                             status_str = "VOID"
                    else:
                        # Legacy API-Football schema check
                        fixture_info = res.get("fixture", {})
                        status_str = fixture_info.get("status", {}).get("short")
                        if status_str in ("FT", "AET", "PEN"):
                            goals = res.get("goals", {})
                            h_goals = goals.get("home", 0)
                            a_goals = goals.get("away", 0)
                            status_str = "FINISHED"

                    if status_str == "FINISHED" and h_goals is not None:
                        if h_goals > a_goals: outcome = "Home"
                        elif a_goals > h_goals: outcome = "Away"
                        else: outcome = "Draw"

                        prediction_won = (outcome == row["market_side"])
                        status = "WON" if prediction_won else "LOST"
                        stake = row["recommended_stake"] or 0.0
                        profit_loss = stake * (row["market_odds"] - 1) if status == "WON" else -stake

                        await conn.execute("""
                            UPDATE football_predictions
                            SET status = $1, actual_score = $2, actual_outcome = $3,
                                profit_loss = $4, updated_at = NOW()
                            WHERE id = $5
                        """, status, f"{h_goals}-{a_goals}", outcome, profit_loss, row["id"])

                        logger.info("FootballEval: Resolved %s as %s (Outcome: %s)", row["fixture_id"], status, outcome)

                    elif status_str in ("VOID", "CANC", "PST", "ABD", "CANCELLED", "POSTPONED"):
                        await conn.execute("""
                            UPDATE football_predictions
                            SET status = 'VOID', updated_at = NOW()
                            WHERE id = $1
                        """, row["id"])
                        logger.info("FootballEval: Voided %s (Status: %s)", row["fixture_id"], status_str)

                except Exception as e:
                    logger.error("FootballEval: Error resolving fixture %s: %s", row["fixture_id"], e)

    except Exception as e:
        logger.error("FootballEval: Result collector error: %s", e)

async def get_performance_stats() -> str:
    """Calculate ROI, Hit Rate, and latest performance metrics."""
    pool = await _get_pool()
    if not pool:
        return "Database not configured."

    try:
        async with pool.acquire() as conn:
            summary = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'WON') as wins,
                    COUNT(*) FILTER (WHERE status = 'LOST') as losses,
                    SUM(profit_loss) as total_pl,
                    SUM(recommended_stake) FILTER (WHERE status IN ('WON', 'LOST')) as total_wagered
                FROM football_predictions
                WHERE status IN ('WON', 'LOST')
                AND created_at > NOW() - INTERVAL '30 days'
            """)

            if not summary or summary["total"] == 0:
                return "Seahorse Performance (30D)\n\nNo resolved predictions yet."

            total = summary["total"]
            wins = summary["wins"]
            pl = summary["total_pl"] or 0.0
            wagered = summary["total_wagered"] or 1.0

            hit_rate = (wins / total) if total > 0 else 0
            roi = (pl / wagered) if wagered > 0 else 0

            recent_rows = await conn.fetch("""
                SELECT match_name, status, profit_loss
                FROM football_predictions
                WHERE status IN ('WON', 'LOST')
                ORDER BY created_at DESC
                LIMIT 5
            """)

            recent_str = ""
            for r in recent_rows:
                tag = "WON" if r["status"] == "WON" else "LOST"
                recent_str += f"[{tag}] {r['match_name']}: {r['profit_loss']:+.1f}u\n"

        return (
            f"Seahorse Performance (30D)\n\n"
            f"Hit Rate: {hit_rate:.1%} ({wins}/{total})\n"
            f"Total P/L: {pl:+.1f} units\n"
            f"ROI: {roi:.1%}\n\n"
            f"Recent Results:\n{recent_str}"
        )

    except Exception as e:
        logger.error("FootballEval: Performance stats error: %s", e)
        return f"Error fetching stats: {e}"
