"""ECharts visualization tool — generates premium charts using native Charming (Rust) engine.

Bridges the seahorse_ffi.PyChartGenerator with the Telegram adapter for image rendering.

Fixed: Added proper category extraction to prevent "Can't extract `str` to `Vec`" error.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Directory for temporary charts
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)

try:
    import seahorse_ffi

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False


@tool(
    "Generate a PREMIUM, interactive business chart using the native ECharts engine. "
    "Input: title (string), categories (list of labels), values (list of numbers), type ('bar' or 'line')."
)
async def native_echarts_chart(
    title: str,
    categories: list[str] | str | None = None,
    values: list[float] | float | None = None,
    chart_type: str = "bar",
) -> str:
    """Generate ECharts JSON and return the path to the rendered image (or JSON if rendering fails).

    Fixed: Properly handle categories as string or list to prevent extraction errors.
    """
    if not _NATIVE_AVAILABLE:
        return "Error: Native ECharts engine (seahorse_ffi) is not available."

    try:
        # Safely extract categories (handle both string and list)
        safe_categories = _extract_categories_safe(categories)
        safe_values = _extract_values_safe(values)

        gen = seahorse_ffi.PyChartGenerator()

        if chart_type.lower() == "line":
            chart_json = gen.line_chart(title, safe_categories, safe_values)
        else:
            # Default to bar
            chart_json = gen.bar_chart(title, safe_categories, safe_values)

        # ── PREMIUM POST-PROCESSING ──
        import json

        try:
            option = json.loads(chart_json)
            # 1. Global Thai Font & Theme Colors
            option["color"] = ["#0062ff", "#00d9ff", "#7000ff", "#ff0070", "#fbbf24", "#ef4444"]
            option["textStyle"] = {"fontFamily": "IBMPlexSansThai, sans-serif"}

            # 2. Modern Series Styling
            if "series" in option and isinstance(option["series"], list):
                for s in option["series"]:
                    if s.get("type") == "bar":
                        s["itemStyle"] = {"borderRadius": [8, 8, 0, 0]}
                    elif s.get("type") == "line":
                        s["smooth"] = True
                        s["lineStyle"] = {"width": 3}

            # 3. Clean Grid & Legends
            option["grid"] = {
                "left": "5%",
                "right": "5%",
                "bottom": "10%",
                "top": "15%",
                "containLabel": True,
            }
            if "legend" in option:
                option["legend"]["itemGap"] = 20

            chart_json = json.dumps(option)
        except Exception as py_e:
            logger.warning("native_echarts: post-processing failed, using raw: %s", py_e)

        filename = f"echart_{uuid.uuid4().hex[:8]}.json"
        filepath = os.path.join(CHART_DIR, filename)

        with open(filepath, "w") as f:
            f.write(chart_json)

        logger.info("native_echarts: generated premium chart config at %s", filepath)

        # Return special prefix so Telegram adapter knows how to handle it
        return f"ECHART_JSON:{filepath}"

    except Exception as e:
        logger.error("native_echarts: generation failed: %s", e)
        return f"Error: Chart generation failed: {e}"


def _extract_categories_safe(categories: list[str] | str | None) -> list[str]:
    """Safely extract categories, handling both string and list input."""
    if categories is None:
        return []
    if isinstance(categories, str):
        return [categories]
    if isinstance(categories, list):
        return [str(c) for c in categories]
    return []


def _extract_values_safe(values: list[float] | float | None) -> list[float]:
    """Safely extract values, handling both single value and list input."""
    if values is None:
        return []
    if isinstance(values, (int, float)):
        return [float(values)]
    if isinstance(values, list):
        return [float(v) for v in values]
    return []
