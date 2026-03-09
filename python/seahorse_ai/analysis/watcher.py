"""seahorse_ai.analysis.watcher — Background service for detecting anomalies."""
from __future__ import annotations
import logging
import asyncio
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from seahorse_ai.schemas import Message
from seahorse_ai.tools.viz import generate_business_chart
from seahorse_ai.tools.forecaster import forecast_sales

logger = logging.getLogger(__name__)

PG_URI = "postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise"

class AnomalyWatcher:
    """Service that periodically scans the DB for business-critical changes."""
    
    def __init__(self, llm_backend: object):
        self._llm = llm_backend
        self._is_running = False
        # To avoid spamming the same alert repeatedly
        self._sent_alerts: set[str] = set()

    async def start(self, interval_seconds: int = 3600):
        """Start the background monitoring loop."""
        self._is_running = True
        logger.info("AnomalyWatcher: starting background loop (interval: %ds)", interval_seconds)
        while self._is_running:
            try:
                await self._check_for_anomalies()
            except Exception as e:
                logger.error("AnomalyWatcher loop error: %s", e)
            await asyncio.sleep(interval_seconds)

    async def stop(self):
        self._is_running = False

    async def _check_for_anomalies(self):
        """Execute health-check queries and use LLM to decide if it's an anomaly."""
        logger.info("AnomalyWatcher: running health checks...")
        
        # 1. Gather data: Compare last 24h vs previous 24h
        stats = self._get_comparison_data()
        if not stats:
            return

        # 2. Ask LLM to analyze
        prompt = (
            "Analyze these sales stats for a business. "
            "Identify if there is any SIGNIFICANT anomaly (e.g., >30% drop in revenue or specific branch failing). "
            "Business Rules:\n"
            "- CRITICAL: Ignore 100% drops or massive drops on weekends (Saturday/Sunday) for branches located in office buildings (e.g., Silom Complex, All Seasons Place, Sathorn Square, Empire Tower, Interchange 21). This is expected behavior because offices are closed.\n"
            "- Focus only on severe and unexpected drops on weekdays or for non-office branches.\n"
            "Return JSON: { \"is_anomaly\": bool, \"severity\": \"low\"|\"high\", \"title\": \"Short Title\", \"reason\": \"Explanation\" }\n\n"
            f"DATA: {json.dumps(stats, indent=2)}"
        )
        
        try:
            # Type ignore since we use protocol in planner but object here
            result = await self._llm.complete( # type: ignore
                [Message(role="user", content=prompt)],
                tier="worker"
            )
            
            # Extract content from the response
            content = ""
            if isinstance(result, dict):
                content = result.get("content", "")
            else:
                content = str(result)
            
            # Robustly parse JSON (handle markdown backticks)
            clean_content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_content)
            
            if data.get("is_anomaly"):
                title = data.get("title", "Unknown Anomaly")
                
                # Check if we already alerted this specific title
                if title not in self._sent_alerts:
                    # Mark as alerted immediately to prevent duplicates from concurrent runs
                    self._sent_alerts.add(title)
                    logger.warning("🚨 ANOMALY DETECTED: %s - %s", title, data.get("reason"))
                    
                    # 3. Generate visual context: find the branch mentioned
                    image_path = None
                    try:
                        # Simple heuristic: find branch name in stats that changed most
                        worst_branch = None
                        max_drop = -1.0
                        for s in stats:
                            drop = s['revenue_prev_24h'] - s['revenue_24h']
                            if drop > max_drop:
                                max_drop = drop
                                worst_branch = s['name']
                        
                        if worst_branch:
                            trend_data = self._get_historical_trend(worst_branch)
                            if trend_data:
                                # A) Generate Chart
                                image_path = generate_business_chart(
                                    data=trend_data,
                                    x_col="date",
                                    y_col="revenue",
                                    title=f"7-Day Revenue Trend: {worst_branch}",
                                    chart_type="line"
                                )
                                
                                # B) Predictive Analysis
                                forecast = forecast_sales(trend_data)
                                if "error" not in forecast:
                                    risk_amount = forecast.get("total_predicted_revenue", 0)
                                    data["reason"] += (
                                        f"\n\n🔮 **Predictive Impact:** Estimated revenue "
                                        f"at risk for next 7 days: ฿{risk_amount:,.2f}"
                                    )
                    except Exception as e:
                        logger.error("Failed to generate anomaly visuals/forecast: %s", e)
                    
                    # Add the generated image path to the payload before notifying
                    if image_path:
                        data["image_paths"] = [image_path]
                        
                    await self._notify(data)
                else:
                    logger.info("Skipping duplicate alert: %s", title)
            else:
                # Clear alerts if everything returns to 'normal' (optional logic)
                # For now, we clear if LLM says no anomaly to allow future re-triggers
                self._sent_alerts.clear()
                
        except Exception as e:
            logger.error("AnomalyWatcher LLM analysis failed: %s", e)

    def _get_comparison_data(self) -> list[dict]:
        """Fetch raw numbers from PG."""
        try:
            conn = psycopg2.connect(PG_URI)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Simple query: revenue per branch in last 24h vs previous 24h
            query = """
                WITH daily_sales AS (
                    SELECT 
                        branch_id,
                        SUM(CASE WHEN transaction_date > NOW() - INTERVAL '24 HOURS' 
                            THEN total_amount ELSE 0 END) as revenue_24h,
                        SUM(CASE WHEN transaction_date <= NOW() - INTERVAL '24 HOURS' 
                            AND transaction_date > NOW() - INTERVAL '48 HOURS' 
                            THEN total_amount ELSE 0 END) as revenue_prev_24h
                    FROM transactions
                    WHERE transaction_date > NOW() - INTERVAL '48 HOURS'
                    GROUP BY branch_id
                )
                SELECT b.name, s.revenue_24h, s.revenue_prev_24h
                FROM daily_sales s
                JOIN branches b ON s.branch_id = b.id;
            """
            cursor.execute(query)
            rows = cursor.fetchall() or []
            conn.close()
            
            # Convert Decimals to floats for JSON serialization
            results = []
            for r in rows:
                d = dict(r)
                d['revenue_24h'] = float(d['revenue_24h'] or 0)
                d['revenue_prev_24h'] = float(d['revenue_prev_24h'] or 0)
                results.append(d)
            return results
        except Exception as e:
            logger.error("Watcher DB query failed: %s", e)
            return []

    def _get_historical_trend(self, branch_name: str) -> list[dict]:
        """Fetch last 7 days of daily revenue for a specific branch."""
        try:
            conn = psycopg2.connect(PG_URI)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = """
                SELECT 
                    transaction_date::date as date,
                    SUM(total_amount) as revenue
                FROM transactions t
                JOIN branches b ON t.branch_id = b.id
                WHERE b.name = %s
                  AND transaction_date > NOW() - INTERVAL '7 DAYS'
                GROUP BY 1
                ORDER BY 1 ASC;
            """
            cursor.execute(query, (branch_name,))
            rows = cursor.fetchall() or []
            conn.close()
            
            return [{"date": str(r['date']), "revenue": float(r['revenue'] or 0)} for r in rows]
        except Exception as e:
            logger.error("Watcher trend query failed for %s: %s", branch_name, e)
            return []

    async def _notify(self, anomaly_data: dict):
        """Dispatch notification to Discord (Placeholder for now)."""
        # In a real impl, this would call the Discord bot directly or via a queue
        # For now, we'll log it specifically for the user to see in logs
        logger.info("ANOMALY_ALERT_DISCORD: %s", json.dumps(anomaly_data, ensure_ascii=False))
