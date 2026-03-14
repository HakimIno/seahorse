import json
import logging
import os

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.football_cache import get_fixture_info, set_fixture_info
from seahorse_ai.tools.football_schemas import (
    APIFootballResponse,
    FullMatchData,
    OddsResponse,
    PredictionData,
)
from seahorse_ffi import fetch_football_data

logger = logging.getLogger(__name__)

# Mapping from API-Football League names/IDs to The Odds API sport_keys
LEAGUE_TO_SPORT_KEY = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_1",
    "UEFA Champions League": "soccer_uefa_champions_league",
    "UEFA Europa League": "soccer_uefa_europa_league",
    "Major League Soccer": "soccer_usa_mls",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Primeira Liga": "soccer_portugal_primeira_liga",
}

def getsportkey(leaguename: str) -> str | None:
    """Helper to map league name to The Odds API sport key."""
    for name, key in LEAGUE_TO_SPORT_KEY.items():
        if name.lower() in leaguename.lower() or leaguename.lower() in name.lower():
            return key
    return None


@tool("Search for a fixture ID by team name, league name, and date.")
def searchfixture(teamname: str, date: str, leaguename: str | None = None) -> str:
    """
    Search for a fixture_id using team name and date (YYYY-MM-DD).
    
    Args:
        teamname: Representative team name (e.g., 'Arsenal').
        date: The date of the match in YYYY-MM-DD format.
        leaguename: Optional league name to filter by (e.g., 'Premier League').
    """
    # For now we'll focus on caching the fixtures found for a specific date
    cache_key = f"search_{teamname}_{leaguename}_{date}"
    cached = get_fixture_info(cache_key)
    if cached:
        return json.dumps(cached, indent=2)

    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://v3.football.api-sports.io/fixtures?date={date}"
    try:
        raw_json = fetch_football_data(url, api_key)
        data = json.loads(raw_json)
        
        # Optimization: Filter at dictionary level before heavy Pydantic model creation
        raw_response = data.get("response", [])
        matches = []
        
        # Check if this is a general search for all matches
        is_all = teamname.upper() == "ALL"
        search_term = teamname.lower().strip() if not is_all else ""
        target_league = leaguename.lower().strip() if leaguename else None
        
        logger.info(f"Filtering {len(raw_response)} matches for '{teamname}' (League: {leaguename}) on {date}")

        for res in raw_response:
            home_data = res.get("teams", {}).get("home", {})
            away_data = res.get("teams", {}).get("away", {})
            home_name = home_data.get("name", "").lower()
            away_name = away_data.get("name", "").lower()
            
            curr_league = res.get("league", {}).get("name", "").lower()

            # Match logic: either it's an "ALL" search, or the team name matches
            match_found = is_all
            if not is_all and search_term and (
                (home_name and (search_term in home_name or home_name in search_term)) or
                (away_name and (search_term in away_name or away_name in search_term))
            ):
                match_found = True
            
            # League Filter (if provided)
            if match_found and target_league and target_league not in curr_league and curr_league not in target_league:
                match_found = False

            if match_found:
                try:
                    # Full validation only for matches
                    fixture_data = FullMatchData(**res)
                    matches.append({
                        "fixture_id": fixture_data.fixture.id,
                        "match": f"{fixture_data.teams['home'].name} vs {fixture_data.teams['away'].name}",
                        "status": fixture_data.fixture.status.long,
                        "league": fixture_data.league.name,
                        "country": fixture_data.league.country
                    })
                except Exception as ve:
                    logger.warning(f"Validation error for fixture {res.get('fixture', {}).get('id')}: {ve}")
    
        logger.info(f"Found {len(matches)} matches for '{teamname}'")
        if not matches:
            return f"ไม่พบข้อมูลการแข่งขันของ {teamname} {(f'ใน {leaguename}') if leaguename else ''} ในวันที่ {date} ครับ"
            
        set_fixture_info(cache_key, matches)
        return json.dumps(matches, indent=2)
    except Exception as e:
        logger.error(f"Error searching fixture: {e}")
        return f"Error searching fixture: {e}"


@tool("Get upcoming fixtures for a specific league and date.")
def getupcomingfixtures(leagueid: int, date: str) -> str:
    """
    Fetch all fixtures for a league on a specific date.
    
    Args:
        leagueid: API-Football league ID (e.g., 39 for EPL).
        date: Date in YYYY-MM-DD format.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://v3.football.api-sports.io/fixtures?league={leagueid}&date={date}&season=2025"
    try:
        raw_json = fetch_football_data(url, api_key)
        # We just return the raw JSON for the scanner to process
        return raw_json
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
    Perform a simple Poisson-based prediction for a match outcome.
    """
    import math

    def poisson(k, lamb):
        return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

    # Simplified prediction logic
    home_win_prob = 0.0
    away_win_prob = 0.0
    draw_prob = 0.0

    max_goals = 6
    for h in range(max_goals):
        for a in range(max_goals):
            prob = poisson(h, homeavgxg) * poisson(a, awayavgxg)
            if h > a:
                home_win_prob += prob
            elif a > h:
                away_win_prob += prob
            else:
                draw_prob += prob

    prediction = {
        "match": f"{hometeam} vs {awayteam}",
        "probabilities": {
            "Home Win": f"{home_win_prob:.2%}",
            "Draw": f"{draw_prob:.2%}",
            "Away Win": f"{away_win_prob:.2%}"
        },
        "most_likely_score": "2-1" if homeavgxg > awayavgxg else "1-2"
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
    Fetch real match intelligence including predictions and lineups.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found."

    url = f"https://v3.football.api-sports.io/predictions?fixture={fixtureid}"
    try:
        raw_json = fetch_football_data(url, api_key)
        data = json.loads(raw_json)
        response = APIFootballResponse(**data)
        
        if not response.response:
            return "No intelligence found for this match."
            
        prediction = PredictionData(**response.response[0])
        # Default to condensed output to save tokens/context
        return _condense_intel(prediction.model_dump_json())
    except Exception as e:
        return f"Error fetching match intel: {e}"


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
        raw_json = fetch_football_data(url, "") # API key is in URL
        return _condense_multi_odds(raw_json)
    except Exception as e:
        return f"Error comparing market odds: {e}"

@tool("Fetch real-time match data from API-Football using the high-performance Rust fetcher.")
def fetchlivematch(fixtureid: int) -> str:
    """
    Fetch live match details including goals, teams, and status.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found in environment."

    url = f"https://v3.football.api-sports.io/fixtures?id={fixtureid}"
    
    try:
        # 1. Fetch via Rust (Rate-Limited)
        raw_json = fetch_football_data(url, api_key)
        data = json.loads(raw_json)
        
        # 2. Validate via Pydantic
        response = APIFootballResponse(**data)
        if not response.response:
            return "No data found for this fixture."
            
        match = FullMatchData(**response.response[0])
        
        return match.model_dump_json(indent=2)
    except Exception as e:
        return f"Error fetching live match: {e}"

@tool("Fetch real-time odds for a specific match.")
def fetchliveodds(fixtureid: int) -> str:
    """
    Fetch market odds for a match.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        return "Error: FOOTBALL_API_KEY not found in environment."

    url = f"https://v3.football.api-sports.io/odds?fixture={fixtureid}"
    
    try:
        raw_json = fetch_football_data(url, api_key)
        data = json.loads(raw_json)
        
        response = APIFootballResponse(**data)
        if not response.response:
            return "No odds found for this fixture."
            
        odds = OddsResponse(**response.response[0])
        
        return _condense_odds(odds.model_dump_json())
    except Exception as e:
        return f"Error fetching live odds: {e}"


# --- Condensation Helpers ---

def _condense_intel(raw_json: str) -> str:
    """Extract only win %, xG, and key stats to save tokens."""
    try:
        data = json.loads(raw_json)
        pred = data.get("predictions", {})
        comp = data.get("comparison", {})
        
        # Extract win probabilities
        resp = f"Win%: H:{pred.get('winner', {}).get('comment', 'N/A')} "
        resp += f"(Home:{pred.get('percent', {}).get('home')} Draw:{pred.get('percent', {}).get('draw')} Away:{pred.get('percent', {}).get('away')}) "
        
        # Extract comparison/intensity
        resp += f"Attack:{comp.get('att', {}).get('home')}/{comp.get('att', {}).get('away')} "
        resp += f"Defense:{comp.get('def', {}).get('home')}/{comp.get('def', {}).get('away')} "
        return resp
    except Exception:
        return raw_json[:500]


def _condense_odds(raw_json: str) -> str:
    """Extract best individual odds from single match fetch."""
    try:
        data = json.loads(raw_json)
        # Handle list or dict
        if isinstance(data, list) and data:
            data = data[0]
        
        bookmakers = data.get("bookmakers", [])
        if not bookmakers:
            return "No odds found."
        
        # Just grab the first bookmaker's 1X2 market to keep it tiny
        bm = bookmakers[0]
        market = next((m for m in bm.get("bets", []) if m.get("name") == "Match Winner"), {})
        values = {v.get("value"): v.get("odd") for v in market.get("values", [])}
        return f"Market({bm.get('name')}): 1:{values.get('Home')} X:{values.get('Draw')} 2:{values.get('Away')}"
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
