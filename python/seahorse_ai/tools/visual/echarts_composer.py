from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Directory for temporary charts
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)


@tool(
    "Compose a PREMIUM, professional ECharts visualization using a full ECharts 'option' dictionary. "
    "Designed for high-end business intelligence reports.\n\n"
    "PARAMETERS:\n"
    "- option: A complete ECharts 'option' dictionary (JSON-compatible).\n\n"
    "DESIGN RULES (CRITICAL):\n"
    "1. FONT: ALWAYS use 'IBMPlexSansThai' for all text elements (title, axisLabel, legend).\n"
    "2. COLORS: Use modern palettes: ['#0062ff', '#00d9ff', '#7000ff', '#ff0070'].\n"
    "3. BARS: Use rounded corners: itemStyle: { borderRadius: [10, 10, 0, 0] }.\n"
    "4. LINES: Use smooth curves: series: { smooth: true, lineStyle: { width: 3 } }.\n"
    "5. GRID: Use containLabel: true and generous padding.\n"
    "6. Use only JSON-serializable structures (no JS functions)."
)
async def echarts_composer(option: dict[str, Any]) -> str:
    """Save the ECharts option as JSON and return the ECHART_JSON prefix for rendering."""
    try:
        if not option:
            return "Error: option is empty."

        # If it's a string, parse it as JSON
        if isinstance(option, str):
            try:
                option = json.loads(option)
            except Exception as e:
                return f"Error: Failed to parse option string as JSON: {e}"

        if not isinstance(option, dict):
            return f"Error: option must be a dictionary, got {type(option).__name__}"

        # Ensure we have a default responsive size if not specified
        # (The rendering template sets 1200x700, but we can hint layout here)
        if "grid" not in option:
            option["grid"] = {
                "left": "5%",
                "right": "5%",
                "bottom": "10%",
                "top": "15%",
                "containLabel": True,
            }

        filename = f"composer_{uuid.uuid4().hex[:8]}.json"
        filepath = os.path.join(CHART_DIR, filename)

        with open(filepath, "w") as f:
            f.write(json.dumps(option, indent=2))

        logger.info("echarts_composer: generated custom chart config at %s", filepath)

        # Return special prefix so Telegram adapter knows how to handle it
        return f"ECHART_JSON:{filepath}"

    except Exception as e:
        logger.error("echarts_composer: failed to save config: %s", e)
        return f"Error: Chart composition failed: {e}"
