import json
import logging
import os
import re
import uuid
import contextlib

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd

matplotlib.use('Agg')  # Headless backend for Discord bot

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Directory for temporary charts
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)

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


@tool(
    "Generates a HIGHLY CUSTOMIZED, premium business chart by executing Matplotlib Python code. "
    "You provide the custom plotting logic, which will be executed in a sandboxed environment.\n\n"
    "ENVIRONMENT SETUP (Already provided, DO NOT import these):\n"
    "- `pd`, `np`, `plt` are already imported.\n"
    "- `df` (Pandas DataFrame) and `data` (List of dicts) contain the findings.\n"
    "- Use `df` for vector operations, or `data` for list comprehensions.\n"
    "- A modern `fig, ax` (12x7, white bg, spines removed) are already created.\n"
    "- `prop_reg` and `prop_bold` are provided for Thai/premium typography.\n"
    "- A professional, corporate color list `bar_colors` (slate, navy, muted blue) is provided.\n\n"
    "YOUR CODE MUST ONLY PLOT ON `ax` (e.g., `ax.plot()`, `ax.bar()`, `ax.fill_between()`).\n"
    "DO NOT call `plt.show()` or `fig.savefig()`. The system handles rendering and saving.\n"
    "ALWAYS set beautiful titles and labels using `prop_bold` and `prop_reg`.\n"
    "Make the chart look extremely professional, using alpha for layers.\n"
    "Use a minimal, elegant, pastel color palette "
    "(e.g., soft pinks, blues, greens, yellows). "
    "Avoid harsh, dark, or generic bright colors.\n"
    "Keep the aesthetic clean, luxurious, and easy on the eyes.\n"
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
        json_match = re.search(r'(\[.*\]|\{.*\})', data_json.strip(), re.DOTALL)
        if not json_match:
            logger.warning(
                "viz: No valid JSON structure found in %s...",
                data_json[:100]
            )
            return "Chart Generation Error: No valid data found."
            
        s_data = json_match.group(1)
        data = json.loads(s_data)
        df = pd.DataFrame(data)

        # 2. Setup Premium Canvas
        if prop_reg:
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = [
                prop_reg.get_name(), 'DejaVu Sans', 'Arial', 'sans-serif'
            ]
            plt.rcParams['axes.unicode_minus'] = False # Fix minus sign with custom fonts
            
        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#ffffff')
        
        # Minimal, elegant pastel color palette
        bar_colors = [
            '#aec6cf', '#ffb3ba', '#b3ecc6', '#fdfd96', '#cbb3cf',
            '#ffd1b3', '#b3e6e6', '#e6cce6', '#d9ead3'
        ]
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#d1d5db')
        ax.spines['bottom'].set_color('#d1d5db')
        ax.grid(axis='y', linestyle='--', alpha=0.5, color='#e5e7eb', zorder=0)

        # 3. Execution Environment
        sandbox_env = {
            "pd": pd,
            "np": np,
            "plt": plt,
            "df": df,
            "data": data,  # Provide raw data for list comprehensions
            "fig": fig,
            "ax": ax,
            "prop_reg": prop_reg,
            "prop_bold": prop_bold,
            "bar_colors": bar_colors,
        }

        # 4. Clean and Execute AI Code
        # Remove markdown wraps from code
        code_clean = python_code.strip()
        if code_clean.startswith("```python"):
            code_clean = code_clean[9:]
        if code_clean.startswith("```"):
            code_clean = code_clean[3:]
        if code_clean.endswith("```"):
            code_clean = code_clean[:-3]
        
        # Execute plotting logic
        exec(code_clean, sandbox_env)

        # 5. Render and Save
        fig.tight_layout()
        filename = f"custom_chart_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(CHART_DIR, filename)
        plt.savefig(filepath, dpi=200, bbox_inches='tight')
        plt.close(fig)
        
        logger.info(f"viz: Custom chart generated at {filepath}")
        return filepath

    except Exception as e:
        logger.error(
            "viz: Failed to generate custom chart. Error: %s\nCode:\n%s...",
            e, python_code[:200]
        )
        # Close the corrupt figure
        with contextlib.suppress(BaseException):
            plt.close()
        return f"Chart Generation Error: {e}"
