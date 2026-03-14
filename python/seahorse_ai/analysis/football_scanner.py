import asyncio
import datetime
import json
import logging
import os

import httpx
from seahorse_ai.tools.football_stats import (
    fetchliveodds,
    getmatchintel,
    getupcomingfixtures,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("football_scanner")

class FootballScanner:
    def __init__(self):
        self.api_key = os.environ.get("FOOTBALL_API_KEY")
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN_FOOTBALL")
        self.chat_id = os.environ.get("TELEGRAM_ALERTS_FOOTBALL_CHAT_ID")
        # Major Leagues: EPL(39), La Liga(140), Bundesliga(78), Serie A(135), Ligue 1(61)
        self.leagues = [39, 140, 78, 135, 61]
        self.sent_alerts = set()
        self.is_running = False

    async def start(self, interval_seconds: int = 1800):
        """Start the background scanning loop."""
        if not self.api_key or not self.telegram_token or not self.chat_id:
            logger.error("FootballScanner: Missing environment variables (API_KEY, TELEGRAM_BOT_TOKEN_FOOTBALL, or TELEGRAM_ALERTS_FOOTBALL_CHAT_ID).")
            return

        self.is_running = True
        logger.info(f"FootballScanner: Starting loop (interval: {interval_seconds}s)")

        while self.is_running:
            try:
                await self.scan()
            except Exception as e:
                logger.error(f"FootballScanner loop error: {e}")
            await asyncio.sleep(interval_seconds)

    async def scan(self):
        """Scan all configured leagues for value bets."""
        today = datetime.date.today().strftime("%Y-%m-%d")
        logger.info(f"FootballScanner: Scanning leagues for {today}...")

        for league_id in self.leagues:
            try:
                # Use tool to fetch fixtures (Synchronous)
                fixtures_raw = getupcomingfixtures(league_id, today)
                data = json.loads(fixtures_raw)
                
                for res in data.get("response", []):
                    fid = res['fixture']['id']
                    if fid in self.sent_alerts:
                        continue
                    
                    status = res['fixture']['status']['short']
                    if status != "NS": # Only scan matches that haven't started
                        continue

                    # Deep Analyze for Value
                    await self._analyze_fixture(fid, res)
            except Exception as e:
                logger.error(f"Error scanning league {league_id}: {e}")

    async def _analyze_fixture(self, fid: int, fixture_data: dict):
        """Perform deep analysis on a specific fixture to find the 'Edge'."""
        try:
            home_team = fixture_data['teams']['home']['name']
            away_team = fixture_data['teams']['away']['name']
            
            # 1. Fetch Intel (Predictions) - Synchronous
            intel_raw = getmatchintel(fid)
            intel = json.loads(intel_raw)
            
            # Extract win probabilities from prediction tool
            # Structure: response[0].predictions.percent.home/draw/away
            # The tool already returns the dumped JSON of the first response item
            probs = intel.get("predictions", {}).get("percent", {})
            if not probs:
                return

            p_home = float(probs.get("home", "33%").replace("%", "")) / 100
            p_draw = float(probs.get("draw", "33%").replace("%", "")) / 100
            p_away = float(probs.get("away", "33%").replace("%", "")) / 100

            # 2. Fetch Market Odds - Synchronous
            odds_raw = fetchliveodds(fid)
            odds_data = json.loads(odds_raw)
            
            # Find 1x2 market
            # response[0].bookmakers[].bets[].values[]
            response_items = odds_data.get("response", [])
            if not response_items:
                return
                
            bookmakers = response_items[0].get("bookmakers", [])
            for bm in bookmakers:
                for bet in bm.get("bets", []):
                    if bet['name'] == "Match Winner":
                        values = {v['value']: float(v['odd']) for v in bet['values']}
                        
                        # Calculate Edge
                        edge_h = (p_home * values.get("Home", 0)) - 1
                        edge_d = (p_draw * values.get("Draw", 0)) - 1
                        edge_a = (p_away * values.get("Away", 0)) - 1

                        results = [
                            ("Home", edge_h, values.get("Home")),
                            ("Draw", edge_d, values.get("Draw")),
                            ("Away", edge_a, values.get("Away"))
                        ]
                        
                        # Sort by edge descending
                        results.sort(key=lambda x: x[1], reverse=True)
                        best_pick, best_edge, best_odds = results[0]

                        if best_edge > 0.10: # God-Level Edge > 10%
                            target_name = home_team if best_pick == "Home" else (away_team if best_pick == "Away" else "Draw")
                            logger.info(f"VALUE FOUND: {home_team} vs {away_team} -> {target_name} @ {best_odds} (Edge: {best_edge:.2%})")
                            await self._send_alert(home_team, away_team, target_name, best_odds, best_edge, fid)
                            self.sent_alerts.add(fid)
                        return
        except Exception as e:
            logger.error(f"Analysis failed for fixture {fid}: {e}")

    async def _send_alert(self, home, away, target, odds, edge, fid):
        message = (
            f"🚨 **GOD-LEVEL VALUE DETECTED!** 🚨\n\n"
            f"🏟️ **Match:** {home} vs {away}\n"
            f"🎯 **Pick:** {target}\n"
            f"📈 **Market Odds:** `{odds:.2f}`\n"
            f"💎 **Estimated Edge:** `{edge*100:.1f}%`\n\n"
            f"Seahorse Quant Model identifies a significant pricing error in this market.\n"
            f"Fixture ID: `{fid}`"
        )
        await self._notify(message)

    async def _notify(self, message):
        if not self.telegram_token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(url, json=payload)
                r.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to send Telegram alert: {e}")

async def main():
    scanner = FootballScanner()
    await scanner.start(interval_seconds=1800)

if __name__ == "__main__":
    asyncio.run(main())
