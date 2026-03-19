"""seahorse_ai.analysis.watcher — Background service for detecting anomalies."""

from __future__ import annotations

import anyio
import json
import logging
import os

import asyncpg

from seahorse_ai.schemas import Message
from seahorse_ai.tools.forecaster import forecast_sales
from seahorse_ai.tools.viz import create_custom_chart

logger = logging.getLogger(__name__)

# Load from environment
PG_URI = os.environ.get("SEAHORSE_PG_URI")


class AnomalyWatcher:
    """Service that periodically scans the DB for business-critical changes."""

    def __init__(self, llm_backend: object) -> None:
        self._llm = llm_backend
        self._is_running = False
        # To avoid spamming the same alert repeatedly
        self._sent_alerts: set[str] = set()

    async def start(self, interval_seconds: int = 3600) -> None:
        """Start the background monitoring loop."""
        if not PG_URI:
            logger.error("AnomalyWatcher: SEAHORSE_PG_URI not set. Monitoring disabled.")
            return

        self._is_running = True
        logger.info("AnomalyWatcher: starting background loop (interval: %ds)", interval_seconds)

        # Ensure persistence table exists
        await self._init_db()

        while self._is_running:
            try:
                await self._check_for_anomalies()
            except Exception as e:
                logger.error("AnomalyWatcher loop error: %s", e)
            await anyio.sleep(interval_seconds)

    async def stop(self) -> None:
        self._is_running = False

    async def _init_db(self) -> None:
        """Create the persistence table for alerts if it doesn't exist."""
        try:
            conn = await asyncpg.connect(PG_URI)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_alerts (
                    id SERIAL PRIMARY KEY,
                    alert_title TEXT UNIQUE,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Load existing alerts into memory cache
            rows = await conn.fetch("SELECT alert_title FROM processed_alerts")
            for r in rows:
                self._sent_alerts.add(r["alert_title"])
            await conn.close()
            logger.info(
                "AnomalyWatcher: Persistence layer initialized (loaded %d alerts)",
                len(self._sent_alerts),
            )
        except Exception as e:
            logger.error("AnomalyWatcher: Failed to initialize persistence table: %s", e)

    async def _check_for_anomalies(self) -> None:
        """Execute health-check queries and use LLM to decide if it's an anomaly."""
        logger.info("AnomalyWatcher: running health checks...")

        # 1. Gather data: Compare last 24h vs previous 24h
        stats = await self._get_comparison_data()
        if not stats:
            return

        # 2. Ask LLM to analyze
        prompt = (
            "Analyze these sales stats for a business. "
            "Identify if there is any SIGNIFICANT anomaly (e.g., >30% drop in revenue or specific branch failing). "
            "Business Rules:\n"
            "- CRITICAL: Ignore 100% drops or massive drops on weekends (Saturday/Sunday) for branches located in office buildings (e.g., Silom Complex, All Seasons Place, Sathorn Square, Empire Tower, Interchange 21). This is expected behavior because offices are closed.\n"
            "- Focus only on severe and unexpected drops on weekdays or for non-office branches.\n"
            'Return JSON: { "is_anomaly": bool, "severity": "low"|"high", "title": "Short Title", "reason": "Explanation" }\n'
            f"DATA: {json.dumps(stats, indent=2)}"
        )

        try:
            result = await self._llm.complete(  # type: ignore
                [Message(role="user", content=prompt)], tier="fast"
            )

            content = ""
            content = result.get("content", "") if isinstance(result, dict) else str(result)

            clean_content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_content)

            if data.get("is_anomaly"):
                title = data.get("title", "Unknown Anomaly")

                if title not in self._sent_alerts:
                    # Persist to DB immediately
                    await self._persist_alert(title)
                    self._sent_alerts.add(title)

                    logger.warning("🚨 ANOMALY DETECTED: %s - %s", title, data.get("reason"))

                    image_path = None
                    try:
                        worst_branch = None
                        max_drop = -1.0
                        for s in stats:
                            drop = s["revenue_prev_24h"] - s["revenue_24h"]
                            if drop > max_drop:
                                max_drop = drop
                                worst_branch = s["name"]

                        if worst_branch:
                            trend_data = await self._get_historical_trend(worst_branch)
                            if trend_data:
                                # Provide code for Area Chart in watcher alert
                                watcher_chart_code = f"""
import pandas as pd
data = {json.dumps(trend_data)}
df = pd.DataFrame(data)
ax.plot(df['date'], df['revenue'].astype(float), marker='o', linewidth=3, markersize=8, color='#ff9999')
ax.fill_between(df['date'], df['revenue'].astype(float), color='#ffb3ba', alpha=0.3)
for i, txt in enumerate(df['revenue'].astype(float)):
    ax.annotate(f"{{f'{{txt:,.0f}}'}}", (df['date'].iloc[i], txt), 
                textcoords="offset points", xytext=(0,12), ha='center', fontsize=10, color='#1f2937', 
                fontweight='bold', fontproperties=prop_bold)
ax.set_title("7-Day Revenue Anomaly Risk: {worst_branch}", fontsize=18, fontweight='bold', pad=25, color='#1f2937', fontproperties=prop_bold)
ax.set_ylabel("Revenue", fontsize=12, color='#4b5563', labelpad=15, fontproperties=prop_reg)
for label in ax.get_xticklabels():
    label.set_fontproperties(prop_reg)
    label.set_fontsize(11)
    label.set_color('#374151')
    label.set_rotation(45)
for label in ax.get_yticklabels():
    label.set_fontproperties(prop_reg)
    label.set_fontsize(11)
    label.set_color('#374151')
ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{{:,}}".format(int(x))))
"""
                                image_path = create_custom_chart(
                                    python_code=watcher_chart_code, data_json=json.dumps(trend_data)
                                )

                                forecast = forecast_sales(trend_data)
                                if "error" not in forecast:
                                    risk_amount = forecast.get("total_predicted_revenue", 0)
                                    data["reason"] += (
                                        f"\n\n🔮 **Predictive Impact:** Estimated revenue "
                                        f"at risk for next 7 days: ฿{risk_amount:,.2f}"
                                    )
                    except Exception as e:
                        logger.error("Failed to generate anomaly visuals/forecast: %s", e)

                    if image_path:
                        data["image_paths"] = [image_path]

                    await self._notify(data)
                else:
                    logger.info("Skipping persistent duplicate alert: %s", title)
            else:
                # Optional: clear if everything returns to normal for a long duration
                pass

        except Exception as e:
            logger.error("AnomalyWatcher LLM analysis failed: %s", e)

    async def _persist_alert(self, title: str) -> None:
        """Save alert title to DB to prevent duplicate notifications after restart."""
        try:
            conn = await asyncpg.connect(PG_URI)
            await conn.execute(
                "INSERT INTO processed_alerts (alert_title) VALUES ($1) ON CONFLICT DO NOTHING",
                title,
            )
            await conn.close()
        except Exception as e:
            logger.error("Failed to persist alert in DB: %s", e)

    async def _get_comparison_data(self) -> list[dict]:
        """Fetch raw numbers using asyncpg."""
        try:
            conn = await asyncpg.connect(PG_URI)
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
            rows = await conn.fetch(query)
            await conn.close()

            results = []
            for r in rows:
                d = dict(r)
                d["revenue_24h"] = float(d["revenue_24h"] or 0)
                d["revenue_prev_24h"] = float(d["revenue_prev_24h"] or 0)
                results.append(d)
            return results
        except Exception as e:
            logger.error("Watcher async DB query failed: %s", e)
            return []

    async def _get_historical_trend(self, branch_name: str) -> list[dict]:
        """Fetch last 7 days of daily revenue using asyncpg."""
        try:
            conn = await asyncpg.connect(PG_URI)
            query = """
                SELECT 
                    transaction_date::date as date,
                    SUM(total_amount) as revenue
                FROM transactions t
                JOIN branches b ON t.branch_id = b.id
                WHERE b.name = $1
                  AND transaction_date > NOW() - INTERVAL '7 DAYS'
                GROUP BY 1
                ORDER BY 1 ASC;
            """
            rows = await conn.fetch(query, branch_name)
            await conn.close()

            return [{"date": str(r["date"]), "revenue": float(r["revenue"] or 0)} for r in rows]
        except Exception as e:
            logger.error("Watcher trend query failed for %s: %s", branch_name, e)
            return []

    async def _notify(self, anomaly_data: dict) -> None:
        """Dispatch notification to Discord."""
        logger.info("ANOMALY_ALERT_DISCORD: %s", json.dumps(anomaly_data, ensure_ascii=False))
