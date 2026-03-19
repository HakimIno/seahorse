"""ECharts visualization tool — generates premium charts using native Charming (Rust) engine.

Bridges the seahorse_ffi.PyChartGenerator with the Telegram adapter for image rendering.
"""

from __future__ import annotations

import logging
import os
import uuid

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
    categories: list[str],
    values: list[float],
    chart_type: str = "bar",
) -> str:
    """Generate ECharts JSON and return the path to the rendered image (or JSON if rendering fails)."""
    if not _NATIVE_AVAILABLE:
        return "Error: Native ECharts engine (seahorse_ffi) is not available."

    try:
        gen = seahorse_ffi.PyChartGenerator()
        
        if chart_type.lower() == "line":
            chart_json = gen.line_chart(title, categories, values)
        else:
            # Default to bar
            chart_json = gen.bar_chart(title, categories, values)
            
        # ── RENDERING ──
        # Phase 1: Output JSON with unique ID for frontend/adapter rendering.
        # Phase 2: Render to PNG if a renderer (e.g. playwright) is available.
        
        filename = f"echart_{uuid.uuid4().hex[:8]}.json"
        filepath = os.path.join(CHART_DIR, filename)
        
        with open(filepath, "w") as f:
            f.write(chart_json)
            
        logger.info("native_echarts: generated chart config at %s", filepath)
        
        # Return special prefix so Telegram adapter knows how to handle it
        return f"ECHART_JSON:{filepath}"
        
    except Exception as e:
        logger.error("native_echarts: generation failed: %s", e)
        return f"Error: Chart generation failed: {e}"
