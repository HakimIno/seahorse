from __future__ import annotations

import datetime
import logging
import math
import os
import time
from typing import TYPE_CHECKING, Any

from seahorse_ai.core.schemas import AgentResponse, Message
from seahorse_ai.planner.fast_utils import robust_json_load
from seahorse_ai.planner.handlers.base import BaseFastHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PolarsHandler(BaseFastHandler):
    """Handles data analysis via Polars and ECharts."""

    async def handle(
        self, prompt: str, history: list[Message] | None, start_t: float, **kwargs: Any
    ) -> AgentResponse | None:
        try:
            today = datetime.date.today().strftime("%Y-%m-%d")
            # 1. Extraction Analysis
            schema = await self._tools.call("database_schema", {})
            files = [
                f for f in os.listdir(".") if f.lower().endswith((".parquet", ".csv", ".json"))
            ]
            if os.path.exists("workspace"):
                files.extend(
                    [
                        f"workspace/{f}"
                        for f in os.listdir("workspace")
                        if f.lower().endswith((".parquet", ".csv", ".json"))
                    ]
                )

            extraction_prompt = f"""
            System Date: {today}
            Database Schema Overview:
            {schema}
            
            Available Workspace Files:
            {files}
            
            Extract logic for Polars analysis and high-end ECharts plotting.
            Return ONLY valid JSON.
            
            - SQL AGGREGATION RULES:
              - DO NOT 'SELECT *' for trend or analysis requests. 
              - Use SQL AGGREGATION (e.g., SUM(total_amount), COUNT(*)) and GROUP BY (e.g., date_trunc('week', timestamp), region) to summarize data.
              - Ensure the WHERE clause covers the full requested timeframe (e.g., BETWEEN '2024-01-01' AND '2024-12-31').
            
            - ECHARTS STYLE RULES (Premium Look):
              - Use modern color palettes: ['#0062ff', '#00d9ff', '#7000ff', '#ff0070'].
              - For Bar charts: set itemStyle.borderRadius = [10, 10, 0, 0].
              - Set grid.containLabel = true and use generous padding.
              - ALWAYS set title.textStyle.fontFamily = 'IBMPlexSansThai'.
            
            JSON Fields:
            - "sql_query": SQL for duckdb_query_json (Must use Aggregation for trends)
            - "chart_title": Title for the chart
            - "chart_type": 'bar' | 'line' | 'scatter'
            - "x_col": X axis dimension
            - "y_col": Aggregated measure
            
            User request: {prompt}
            """

            res = await self._llm.complete(
                [Message(role="user", content=extraction_prompt)], tier="fast"
            )
            data = robust_json_load(str(res.get("content", res) if isinstance(res, dict) else res))

            if not data or not data.get("sql_query"):
                return None

            sql = data.get("sql_query")
            chart_type = data.get("chart_type", "bar")
            x_col = data.get("x_col")
            y_col = data.get("y_col")

            # 2. Querying
            data_res = await self._tools.call(
                "duckdb_query_json", {"sql_query": sql, "max_rows": 10000}
            )
            rows = robust_json_load(data_res)

            if not rows or not isinstance(rows, list):
                logger.warning("PolarsHandler: No data returned for query: %s", sql)
                return None

            viz_result = ""
            analysis_summary = f"Analyzed {len(rows)} records."

            # 3. Chart Generation (Modular Logic)
            if chart_type == "scatter":
                viz_result, analysis_summary = await self._handle_scatter(data, rows, x_col, y_col)
            elif x_col and y_col:
                cats = [str(r.get(x_col)) for r in rows[:20]]
                vals = [float(r.get(y_col, 0)) for r in rows[:20]]
                viz_result = await self._tools.call(
                    "native_echarts_chart",
                    {
                        "title": data.get("chart_title", "Analysis"),
                        "categories": cats,
                        "values": vals,
                        "chart_type": chart_type,
                    },
                )

            # 4. Final synthesis
            instruction = (
                "You are a professional data analyst. Synthesize a concise, helpful final report based on these results.\n\n"
                f"Analysis Summary: {analysis_summary}\n"
                f"Visualization Tag: {viz_result}\n\n"
                "CRITICAL: You MUST include the Visualization Tag (ECHART_JSON:...) "
                "at the VERY END of your response EXACTLY as provided. Do NOT change it."
            )

            msgs = []
            if history:
                msgs.extend(history[-4:])
            msgs.append(Message(role="user", content=instruction))

            final_res = await self._llm.complete(msgs, tier="worker")
            content = str(
                final_res.get("content", final_res) if isinstance(final_res, dict) else final_res
            )

            return AgentResponse(
                content=f"{content}\n\n{viz_result}",
                steps=3,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )

        except Exception as e:
            logger.error(f"PolarsHandler: {e}")
            return None

    async def _handle_scatter(
        self, data: dict, rows: list, x_col: str | None, y_col: str | None
    ) -> tuple[str, str]:
        # Implementation of previous scatter plot logic
        cols = list(rows[0].keys()) if rows else []
        if not x_col and len(cols) >= 1:
            x_col = cols[0]
        if not y_col and len(cols) >= 2:
            y_col = cols[1]

        if not (x_col and y_col):
            return "", "Insufficient columns for scatter plot"

        data_points = []
        for r in rows:
            try:
                data_points.append([float(r.get(x_col, 0)), float(r.get(y_col, 0))])
            except Exception:
                continue

        n = len(data_points)
        subtext = ""
        if n > 1:
            # Correlation formula
            sx, sy, sxx, syy, sxy = 0, 0, 0, 0, 0
            for px, py in data_points:
                sx += px
                sy += py
                sxx += px * px
                syy += py * py
                sxy += px * py
            num = (n * sxy) - (sx * sy)
            den = math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
            corr = num / den if den != 0 else 0
            subtext = f"Pearson Correlation: {corr:.4f} (n={n})"

        option = {
            "title": {"text": data.get("chart_title", f"{x_col} vs {y_col}"), "subtext": subtext},
            "tooltip": {"trigger": "item"},
            "xAxis": {"name": x_col, "type": "value", "scale": True},
            "yAxis": {"name": y_col, "type": "value", "scale": True},
            "series": [
                {
                    "data": data_points[:2000],
                    "type": "scatter",
                    "symbolSize": 6,
                    "itemStyle": {"color": "#00d9ff"},
                }
            ],
        }
        viz = await self._tools.call("echarts_composer", {"option": option})
        return viz, f"Scatter plot generated. {subtext}"
