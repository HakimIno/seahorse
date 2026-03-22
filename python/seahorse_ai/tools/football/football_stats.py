import json
import logging
import os

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.football.football_cache import get_fixture_info, set_fixture_info
from seahorse_ai.tools.football.football_schemas import (
    APIFootballResponse,
    FullMatchData,
    OddsResponse,
    PredictionData,
)
from seahorse_ffi import fetch_football_data

logger = logging.getLogger(__name__)

# Mapping from common names to Football-Data.org Competition Codes
COMPETITION_CODES = {
    "Premier League": "PL",
    "Championship": "ELC",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Eredivisie": "DED",
    "Primeira Liga": "PPL",
    "UEFA Champions League": "CL",
    "European Championship": "EC",
    "World Cup": "WC",
}

def getcompcode(leaguename: str) -> str | None:
    """Helper to map league name to Football-Data.org competition code."""
    for name, code in COMPETITION_CODES.items():
        if name.lower() in leaguename.lower() or leaguename.lower() in name.lower():
            return code
    return None

def getsportkey(leaguename: str) -> str | None:
    """Helper to map league name to The Odds API sport key."""
    # Mapping for The Odds API (EPL, La Liga, etc.)
    ODDS_MAPPING = {
        "PL": "soccer_epl",
        "ELC": "soccer_efl_champ",
        "PD": "soccer_spain_la_liga",
        "SA": "soccer_italy_serie_a",
        "BL1": "soccer_germany_bundesliga",
        "FL1": "soccer_france_ligue_one",
        "DED": "soccer_netherlands_eredivisie",
        "PPL": "soccer_portugal_primeira_liga",
        "CL": "soccer_uefa_champs_league",
    }
    code = getcompcode(leaguename)
    return ODDS_MAPPING.get(code) if code else None

@tool("Calculate average goals (xG proxy) for a team from recent matches.")
def getteamxg(teamid: int) -> str:
    """
    Fetch last 10 finished matches for a team and return average goals scored.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://api.football-data.org/v4/teams/{teamid}/matches?status=FINISHED&limit=10"
    try:
        raw_json = fetch_fd_data(url, api_key)
        data = json.loads(raw_json)
        matches = data.get("matches", [])
        if not matches:
            return "0.0"
        
        total_goals = 0
        count = 0
        for m in matches:
            count += 1
            score = m.get("score", {}).get("fullTime", {})
            if m.get("homeTeam", {}).get("id") == teamid:
                total_goals += score.get("home", 0)
            else:
                total_goals += score.get("away", 0)
        
        avg = total_goals / count if count > 0 else 0.0
        return str(round(avg, 2))
    except Exception as e:
        return f"Error calculating xG: {e}"

def fetch_fd_data(url: str, api_key: str) -> str:
    """Helper to fetch data from Football-Data.org with correct headers."""
    import requests
    headers = {"X-Auth-Token": api_key}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except Exception as e:
        # Avoid error level logging for 400 (Bad Request) as it's common during Migration/Fixture resolution
        if hasattr(e, 'response') and e.response.status_code == 400:
            logger.warning(f"Football-Data.org (400): {url}")
        else:
            logger.error(f"Football-Data.org error ({url}): {e}")
        return f"Error: {e}"


@tool("Search for a fixture ID by team name, league name, and date.")
def searchfixture(teamname: str, date: str, leaguename: str | None = None) -> str:
    """
    Search for a fixture using Football-Data.org.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    code = getcompcode(leaguename) if leaguename else None
    url = f"https://api.football-data.org/v4/matches?dateFrom={date}&dateTo={date}"
    if code:
        url = f"https://api.football-data.org/v4/competitions/{code}/matches?dateFrom={date}&dateTo={date}"

    try:
        raw_json = fetch_fd_data(url, api_key)
        data = json.loads(raw_json)
        matches_raw = data.get("matches", [])
        
        matches = []
        search_term = teamname.lower().strip()
        is_all = search_term == "all"

        for m in matches_raw:
            home = m.get("homeTeam", {}).get("name", "").lower()
            away = m.get("awayTeam", {}).get("name", "").lower()
            
            if is_all or search_term in home or search_term in away:
                matches.append({
                    "fixture_id": m.get("id"),
                    "home_team_id": m.get("homeTeam", {}).get("id"),
                    "away_team_id": m.get("awayTeam", {}).get("id"),
                    "match": f"{m.get('homeTeam', {}).get('name')} vs {m.get('awayTeam', {}).get('name')}",
                    "status": m.get("status"),
                    "league": m.get("competition", {}).get("name"),
                    "country": m.get("area", {}).get("name")
                })
        
        return json.dumps(matches, indent=2)
    except Exception as e:
        return f"Error searching fixture: {e}"


@tool("Search for a league ID (Competition Code) by name.")
def searchleague(name: str, country: str | None = None) -> str:
    """
    Find a competition code (e.g., 'PL').
    """
    code = getcompcode(name)
    if code:
        return json.dumps([{"league_id": code, "name": name}], indent=2)
    return f"No competition code found for '{name}'."


@tool("Get upcoming fixtures for a specific league and date.")
def getupcomingfixtures(leagueid: str | int, date: str) -> str:
    """
    Fetch all fixtures for a league on a specific date using Football-Data.org.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    # leagueid might be a code (PL) or numeric ID
    comp_code = leagueid if isinstance(leagueid, str) and not leagueid.isdigit() else leagueid
    
    url = f"https://api.football-data.org/v4/competitions/{comp_code}/matches?dateFrom={date}&dateTo={date}"
    try:
        raw_json = fetch_fd_data(url, api_key)
        # Wrap in a structure similar to what the bot expects
        data = json.loads(raw_json)
        return json.dumps({"response": data.get("matches", [])})
    except Exception as e:
        return f"Error fetching league fixtures: {e}"


@tool("Get historical head-to-head (H2H) results between two teams.")
def geth2hresults(teamid1: int, teamid2: int) -> str:
    """
    Fetch real H2H data from API-Football.
    
    Args:
        teamid1: ID of the first team.
        teamid2: ID of the second team.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://v3.football.api-sports.io/fixtures/headtohead?h2h={teamid1}-{teamid2}&last=5"
    try:
        raw_json = fetch_football_data(url, api_key)
        data = json.loads(raw_json)
        response = APIFootballResponse(**data)
        
        results = []
        for res in response.response:
            match = FullMatchData(**res)
            results.append({
                "date": match.fixture.date.strftime("%Y-%m-%d"),
                "score": f"{match.teams['home'].name} {match.goals.home}-{match.goals.away} {match.teams['away'].name}",
                "winner": "Home" if match.teams['home'].winner else ("Away" if match.teams['away'].winner else "Draw")
            })
            
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching H2H: {e}"

@tool("Predict the outcome of a football match using a Poisson distribution based on xG scores.")
def predictmatchoutcome(hometeam: str, awayteam: str, homeavgxg: float, awayavgxg: float) -> str:
    """
    Perform a Poisson-based prediction including most-likely score and O/U 2.5.
    """
    from seahorse_ai.analysis.football_eval import compute_poisson_prediction

    poisson = compute_poisson_prediction(homeavgxg, awayavgxg)

    prediction = {
        "match": f"{hometeam} vs {awayteam}",
        "probabilities": {
            "Home Win": f"{poisson['poisson_h']:.2%}",
            "Draw": f"{poisson['poisson_d']:.2%}",
            "Away Win": f"{poisson['poisson_a']:.2%}",
        },
        "most_likely_score": poisson["most_likely_score"],
        "most_likely_score_prob": f"{poisson['most_likely_score_prob']:.2%}",
        "over_2.5": f"{poisson['poisson_over25']:.2%}",
        "under_2.5": f"{poisson['poisson_under25']:.2%}",
    }
    return json.dumps(prediction, indent=2)

@tool("Calculate the 'Value' of a bet by comparing model probability against market odds.")
def calculatebetvalue(modelprobability: float, marketodds: float) -> str:
    """
    Calculate Expected Value (EV).
    """
    ev = (modelprobability * marketodds) - 1
    is_value = ev > 0.05  # Standard 5% edge threshold
    
    result = {
        "expected_value": f"{ev:+.2%}",
        "has_edge": is_value,
        "recommendation": "BET" if is_value else "SKIP"
    }
    return json.dumps(result, indent=2)

@tool("Calculate the optimal bet size using the Kelly Criterion.")
def kellycriterion(modelprobability: float, marketodds: float, bankroll: float, fraction: float = 0.5) -> str:
    """
    Calculate bet size based on edge and odds.
    """
    if marketodds <= 1:
        return "Error: Market odds must be greater than 1."
    
    b = marketodds - 1
    p = modelprobability
    q = 1 - p
    
    # Kelly Formula: f = (bp - q) / b
    f = (b * p - q) / b
    
    recommended_percentage = max(0, f * fraction)
    suggested_stake = bankroll * recommended_percentage
    
    result = {
        "kelly_percentage": f"{f:.2%}",
        "fractional_kelly_applied": f"{fraction}",
        "suggested_stake": f"{suggested_stake:,.2f}",
        "bankroll_impact": f"{recommended_percentage:.2%}"
    }
    return json.dumps(result, indent=2)

@tool("Retrieve real-time lineups, injuries, and predictions for a match.")
def getmatchintel(fixtureid: int) -> str:
    """
    [DEPRECATED] Historical intelligence. Use Poisson model instead.
    """
    return "Intelligence data is now computed internally via Poisson model."


@tool("Compare market odds across multiple bookmakers using The Odds API.")
def comparemarketodds(sportkey: str, regions: str = "uk,eu,us") -> str:
    """
    Fetch and compare odds from The Odds API for better value detection.
    """
    odds_key = os.environ.get("ODDS_API_KEY")
    if not odds_key:
        return "Error: ODDS_API_KEY not found."

    url = f"https://api.the-odds-api.com/v4/sports/{sportkey}/odds/?apiKey={odds_key}&regions={regions}&markets=h2h"
    
    try:
        # Use fetch_fd_data or similar instead of fetch_football_data to avoid headers confusion
        import requests
        response = requests.get(url)
        response.raise_for_status()
        return _condense_multi_odds(response.text)
    except Exception as e:
        return f"Error comparing market odds: {e}"

@tool("Fetch real-time match data from Football-Data.org.")
def fetchlivematch(fixtureid: int) -> str:
    """
    Fetch match details including goals, teams, and status using Football-Data.org.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://api.football-data.org/v4/matches/{fixtureid}"
    try:
        raw_json = fetch_fd_data(url, api_key)
        return raw_json
    except Exception as e:
        return f"Error fetching live match: {e}"

@tool("Fetch real-time odds for a specific match.")
def fetchliveodds(fixtureid: int) -> str:
    """
    Fetch market odds for a match. (Note: Football-Data.org free tier has limited odds).
    """
    # For now, we return a message or try to fetch match details which might have odds
    return "Market odds should be fetched via comparemarketodds for maximum coverage."


# --- Condensation Helpers ---

def _condense_intel(raw_json: str) -> str:
    """Extract win %, xG proxy, and key stats into a condensed JSON string."""
    try:
        data = json.loads(raw_json)
        # We only keep what's necessary for analysis and persist
        condensed = {
            "predictions": data.get("predictions", {}),
            "teams": data.get("teams", {}),
            "comparison": data.get("comparison", {}),
            "league": data.get("league", {}),
            "h2h": data.get("h2h", [])[:5]  # Keep only 5 H2H to save tokens
        }
        return json.dumps(condensed)
    except Exception:
        # Fallback to minimal JSON if parse fails
        return json.dumps({"error": "Failed to parse intelligence", "raw_prefix": raw_json[:200]})


def _condense_odds(raw_json: str) -> str:
    """Extract best odds across ALL bookmakers for 1X2 + Over/Under 2.5."""
    try:
        data = json.loads(raw_json)
        if isinstance(data, list) and data:
            data = data[0]

        bookmakers = data.get("bookmakers", [])
        if not bookmakers:
            return "No odds found."

        best = {"Home": ("", 0.0), "Draw": ("", 0.0), "Away": ("", 0.0)}
        best_ou = {"Over 2.5": ("", 0.0), "Under 2.5": ("", 0.0)}

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
                        if side in best and price > best[side][1]:
                            best[side] = (bm_name, price)
                elif "Over/Under" in bet.get("name", "") or "Goals" in bet.get("name", ""):
                    for val in bet.get("values", []):
                        v = str(val.get("value", ""))
                        try:
                            price = float(val.get("odd", 0))
                        except (ValueError, TypeError):
                            continue
                        if "Over" in v and "2.5" in v and price > best_ou["Over 2.5"][1]:
                            best_ou["Over 2.5"] = (bm_name, price)
                        elif "Under" in v and "2.5" in v and price > best_ou["Under 2.5"][1]:
                            best_ou["Under 2.5"] = (bm_name, price)

        parts = [
            f"1:{best['Home'][1]}({best['Home'][0]})",
            f"X:{best['Draw'][1]}({best['Draw'][0]})",
            f"2:{best['Away'][1]}({best['Away'][0]})",
        ]
        ou_parts = []
        if best_ou["Over 2.5"][1] > 0:
            ou_parts.append(f"O2.5:{best_ou['Over 2.5'][1]}({best_ou['Over 2.5'][0]})")
        if best_ou["Under 2.5"][1] > 0:
            ou_parts.append(f"U2.5:{best_ou['Under 2.5'][1]}({best_ou['Under 2.5'][0]})")

        return "BestOdds " + " ".join(parts) + (" " + " ".join(ou_parts) if ou_parts else "")
    except Exception:
        return raw_json[:300]


def _condense_multi_odds(raw_json: str) -> str:
    """Summarize cross-market odds for multiple matches."""
    try:
        data = json.loads(raw_json)
        if not isinstance(data, list):
            return raw_json[:1000]
            
        summary = []
        # Return only the top 10 matches to keep it within reason
        for match in data[:10]:
            match_name = f"{match.get('home_team')} vs {match.get('away_team')}"
            best_odds = {"1": 0.0, "X": 0.0, "2": 0.0}
            
            for bm in match.get("bookmakers", []):
                for market in bm.get("markets", []):
                    if market.get("key") == "h2h":
                        for outcome in market.get("outcomes", []):
                            price = outcome.get("price")
                            name = outcome.get("name")
                            if name == match.get("home_team"):
                                best_odds["1"] = max(best_odds["1"], price)
                            elif name == match.get("away_team"):
                                best_odds["2"] = max(best_odds["2"], price)
                            else:
                                best_odds["X"] = max(best_odds["X"], price)
            
            summary.append(f"{match_name}: MaxOdds(1:{best_odds['1']} X:{best_odds['X']} 2:{best_odds['2']})")
            
        return "\n".join(summary)
    except Exception:
        return raw_json[:1000]
