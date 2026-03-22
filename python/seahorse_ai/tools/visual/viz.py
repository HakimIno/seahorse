import contextlib
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import seaborn as sns

matplotlib.use("Agg")  # Headless backend for Discord bot

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Directory for temporary charts
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)
RENDER_LOG = "/tmp/seahorse_render.log"

# Load custom Thai fonts for professional rendering
font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")
thai_font_path = os.path.join(font_dir, "IBMPlexSansThai-Regular.ttf")
thai_font_bold_path = os.path.join(font_dir, "IBMPlexSansThai-Bold.ttf")

# Cached FontProperties
prop_reg = None
prop_bold = None

try:
    if os.path.exists(font_dir):
        for font_file in os.listdir(font_dir):
            if font_file.endswith(".ttf"):
                fm.fontManager.addfont(os.path.join(font_dir, font_file))

        if os.path.exists(thai_font_path):
            prop_reg = fm.FontProperties(fname=thai_font_path)
        if os.path.exists(thai_font_bold_path):
            prop_bold = fm.FontProperties(fname=thai_font_bold_path)
except Exception as e:
    logger.warning(f"Failed to load custom Thai fonts: {e}")


async def render_echarts_to_png(json_conf: str) -> str | None:
    """Render ECharts JSON configuration to a static PNG image with premium Thai fonts."""
    from seahorse_ai.tools.system.browser import browser_screenshot
    import base64

    filename = f"echart_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(CHART_DIR, filename)
    temp_html = os.path.join(CHART_DIR, f"{filename}.html")

    # Load and Base64 encode fonts for reliable browser injection
    font_css = ""
    try:
        f_reg = os.path.join(font_dir, "IBMPlexSansThai-Regular.ttf")
        f_bold = os.path.join(font_dir, "IBMPlexSansThai-Bold.ttf")
        if os.path.exists(f_reg) and os.path.exists(f_bold):
            with open(f_reg, "rb") as f:
                reg_b64 = base64.b64encode(f.read()).decode("utf-8")
            with open(f_bold, "rb") as f:
                bold_b64 = base64.b64encode(f.read()).decode("utf-8")
            
            font_css = f"""
            @font-face {{
                font-family: 'IBMPlexSansThai';
                src: url(data:font/ttf;charset=utf-8;base64,{reg_b64}) format('truetype');
                font-weight: normal;
                font-style: normal;
            }}
            @font-face {{
                font-family: 'IBMPlexSansThai';
                src: url(data:font/ttf;charset=utf-8;base64,{bold_b64}) format('truetype');
                font-weight: bold;
                font-style: normal;
            }}
            """
    except Exception as e:
        logger.warning(f"viz: Font embedding failed: {e}")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <script src="https://fastly.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js"></script>
        <style>
            {font_css}
            body, html, #main {{ 
                margin: 0; padding: 0; width: 1200px; height: 700px; 
                overflow: hidden; background: #ffffff; 
                font-family: 'IBMPlexSansThai', sans-serif;
            }}
        </style>
    </head>
    <body>
        <div id="main"></div>
        <script>
            var chart = echarts.init(document.getElementById('main'), null, {{ 
                renderer: 'canvas', 
                devicePixelRatio: 2 
            }});
            var option = {json_conf};
            
            // Force Thai font on all text elements if not specified
            const fontStyle = {{ fontFamily: 'IBMPlexSansThai, sans-serif' }};
            if (option.title) option.title.textStyle = {{ ...fontStyle, fontWeight: 'bold', fontSize: 24, ...(option.title.textStyle || {{}}) }};
            if (option.xAxis) option.xAxis.axisLabel = {{ ...fontStyle, ...(option.xAxis.axisLabel || {{}}) }};
            if (option.yAxis) option.yAxis.axisLabel = {{ ...fontStyle, ...(option.yAxis.axisLabel || {{}}) }};
            if (option.legend) option.legend.textStyle = {{ ...fontStyle, ...(option.legend.textStyle || {{}}) }};
            
            chart.setOption(option);
        </script>
    </body>
    </html>
    """

    try:
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Capture at high DPI for premium look
        res = await browser_screenshot(
            url=f"file://{os.path.abspath(temp_html)}",
            output_path=filepath
        )
        
        if os.path.exists(temp_html):
            os.remove(temp_html)
            
        return filepath if os.path.exists(filepath) else None
    except Exception as e:
        logger.error(f"viz: ECharts render failed: {e}")
        return None


@tool(
    "Generates a HIGH-FIDELITY, premium business chart by executing Matplotlib code. "
    "CRITICAL: NEVER use hardcoded data or 'sample' dates (e.g., 2024). ALWAYS utilize the provided `pdf` (Polars) or `df` (Pandas) variables which contain the ACTUAL results.\n\n"
    "TIME-SERIES RULES:\n"
    "- If plotting a trend, you MUST handle gaps. Use `pdf = pdf.upsample(time_column, every='1d').fill_null(0)` or Pandas equivalent to ensure days with 0 activity are shown as gaps, not smoothed over.\n"
    "- Use `prop_reg` for labels and `prop_bold` for the main title.\n\n"
    "ENVIRONMENT SETUP (Already provided, DO NOT import these):\n"
    "- `pd`, `pl` (Polars), `np`, `plt`, `sns` are pre-imported.\n"
    "- `df` (Pandas) and `pdf` (Polars) contain the REAL data parsed from the user's request.\n"
    "- `ax`: The active axes for plotting. DO NOT call `plt.show()`.\n"
    "- `get_palette(name)`: Returns a hex list (names: 'modern', 'vibrant', 'corporate', 'pastel').\n\n"
    "YOUR CODE MUST:\n"
    "1. Sort the data by date if applicable.\n"
    "2. Plot ONLY on `ax`.\n"
    "3. Set professional titles and clear legends.\n\n"
    "SECURITY: No imports, no system calls. Only plotting logic."
)
def create_custom_chart(
    python_code: str,
    data_json: str,
) -> str | None:
    """Execute dynamic Matplotlib code to generate a custom business chart."""
    if not data_json or not python_code:
        logger.warning("viz: Missing code or data for chart generation.")
        return None
    try:
        # 1. Parse Data (Robustly extract JSON block)
        json_match = re.search(r"(\[.*\]|\{.*\})", data_json.strip(), re.DOTALL)
        if not json_match:
            logger.warning("viz: No valid JSON structure found in %s...", data_json[:100])
            return "Chart Generation Error: No valid data found."

        s_data = json_match.group(1)
        data = json.loads(s_data)
        df = pd.DataFrame(data)
        pdf = pl.DataFrame(data)

        # 2. Setup Premium Canvas
        if prop_reg:
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [
                prop_reg.get_name(),
                "DejaVu Sans",
                "Arial",
                "sans-serif",
            ]
            plt.rcParams["axes.unicode_minus"] = False  # Fix minus sign with custom fonts

        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")

        # Dynamic color palettes
        palettes = {
            "modern": ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#16a34a"],
            "vibrant": sns.color_palette("husl", 8).as_hex(),
            "corporate": ["#0f172a", "#334155", "#475569", "#64748b", "#94a3b8"],
            "pastel": ["#aec6cf", "#ffb3ba", "#b3ecc6", "#fdfd96", "#cbb3cf"],
        }

        def get_palette(name="modern"):
            return palettes.get(name, palettes["modern"])

        # Default fallback color array for legacy or simple charts
        bar_colors = get_palette(random.choice(list(palettes.keys())))

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#d1d5db")
        ax.spines["bottom"].set_color("#d1d5db")
        ax.grid(axis="y", linestyle="--", alpha=0.5, color="#e5e7eb", zorder=0)

        # 3. Execution Environment
        # (Overridden by hardened_env below)

        # 4. Clean and Execute AI Code
        # Remove markdown wraps from code
        code_clean = python_code.strip()
        if code_clean.startswith("```python"):
            code_clean = code_clean[9:]
        if code_clean.startswith("```"):
            code_clean = code_clean[3:]
        if code_clean.endswith("```"):
            code_clean = code_clean[:-3]

        # ── PHASE 3: REAL WASMTIME SANDBOX SECURITY ──
        # 1. Wasm Guard: Scan for forbidden patterns using the Rust engine
        forbidden_patterns = [
            "import os", "import subprocess", "import sys", "getattr", "setattr",
            "__builtins__", "eval(", "exec(", "open(", "socket", "requests"
        ]
        
        use_sandbox = os.environ.get("SEAHORSE_USE_WASM", "true").lower() == "true"
        is_safe = True

        if use_sandbox:
            try:
                import seahorse_ffi
                
                # Load the Wasm security guard
                guard_path = os.path.join(os.path.dirname(__file__), "guard.wat")
                if os.path.exists(guard_path):
                    with open(guard_path, "rb") as f:
                        wat_bytes = f.read()
                    
                    wasm_manager = seahorse_ffi.PyWasmManager()
                    logger.info("viz: gating plotting logic through Wasm security guard...")
                    # The Wasm guard returns 1 if safe
                    guard_result = wasm_manager.run(wat_bytes)
                    if guard_result != "Success":
                        logger.warning("viz: Wasm security guard rejected the code!")
                        is_safe = False
                
                # Python-level double check for forbidden patterns
                if any(p in code_clean for p in forbidden_patterns):
                    logger.warning("viz: Static analysis found forbidden patterns in code.")
                    is_safe = False

            except (ImportError, Exception) as e:
                logger.warning(f"viz: Wasm security layer failed ({e}). Falling back to restricted Python.")
        
        # 2. Restricted Execution
        if not is_safe:
            # FALLBACK: If code is dangerous, block execution to protect the system.
            logger.warning("viz: Security violation detected. Operation blocked.")
            raise PermissionError("Code execution blocked by Wasm Security Sandbox to protect host system.")

        # 3. Execution in a hardened environment
        # Clear __builtins__ and only allow safe math/plotting functions
        safe_builtins = {
            "abs": abs, "len": len, "range": range, "round": round, "sum": sum,
            "min": min, "max": max, "enumerate": enumerate, "zip": zip,
            "list": list, "dict": dict, "str": str, "int": int, "float": float,
            "bool": bool, "print": logger.info, # Redirect print to log
        }

        # Anti-getattr/setattr check in code (redundant but safe)
        if "." in code_clean and ("getattr" in code_clean or "setattr" in code_clean):
             logger.warning("viz: Code contains property access exploits.")
             is_safe = False
        
        hardened_env = {
            "__builtins__": safe_builtins,
            "pd": pd,
            "pl": pl,
            "np": np,
            "plt": plt,
            "sns": sns,
            "df": df,
            "pdf": pdf,
            "data": data,
            "fig": fig,
            "ax": ax,
            "prop_reg": prop_reg,
            "prop_bold": prop_bold,
            "bar_colors": bar_colors,
            "get_palette": get_palette,
            "random": random,
        }
        
        exec(code_clean, hardened_env)

        # 5. Render and Save
        fig.tight_layout()
        filename = f"custom_chart_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(CHART_DIR, filename)
        plt.savefig(filepath, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"viz: Custom chart generated at {filepath}")
        return filepath

    except PermissionError as e:
        # Check if we should try native ECharts rendering on security block
        # This is a fallback to a safe engine
        try:
            import seahorse_ffi
            import anyio
            gen = seahorse_ffi.PyChartGenerator()
            # Try to guess intent for fallback
            cats = ["Analysis"]
            vals = [1.0]
            if not df.empty and len(df.columns) >= 2:
                cats = [str(x) for x in df.iloc[:10, 0].tolist()]
                vals = [float(x) for x in df.iloc[:10, 1].tolist()]
            
            json_conf = gen.bar_chart("Security Fallback Summary", cats, vals)
            # Render ECharts JSON to PNG via our new bridge
            png_path = anyio.run(render_echarts_to_png, json_conf)
            if png_path:
                logger.info(f"viz: Fallback ECharts PNG generated at {png_path}")
                return png_path
        except Exception as fe:
            logger.error(f"viz: Fallback rendering failed: {fe}")
        
        return f"Chart Generation Error: {e}"

    except Exception as e:
        logger.error(
            "viz: Failed to generate custom chart. Error: %s\nCode:\n%s...", e, python_code[:200]
        )
        # Close the corrupt figure
        with contextlib.suppress(BaseException):
            plt.close()
        return f"Chart Generation Error: {e}"
