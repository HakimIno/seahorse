import os
import logging
import uuid
import json
import matplotlib
matplotlib.use('Agg') # Headless backend for Discord bot
import matplotlib.pyplot as plt
import pandas as pd
from typing import List, Dict, Any, Optional
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Directory for temporary charts
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)

import matplotlib.font_manager as fm

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
    "Generates a business chart (bar, line, or pie) from a list of data records. "
    "Use this for visualizing sales trends or distributions. "
    "Returns the file path of the generated PNG image."
)
def generate_business_chart(
    data: List[Dict[str, Any]] | str, 
    x_col: str, 
    y_col: str, 
    title: str, 
    chart_type: str = "bar"
) -> Optional[str]:
    """
    Generates a chart from a list of dictionaries (or JSON string) and saves it as a PNG.
    
    Args:
        data: List of records (e.g., from database_query) or JSON string
        x_col: Column name for X axis
        y_col: Column name for Y axis
        title: Title of the chart
        chart_type: 'bar', 'line', or 'pie'
        
    Returns:
        Path to the generated PNG file, or None if failed.
    """
    if not data:
        logger.warning("viz: No data provided for chart generation.")
        return None

    try:
        if isinstance(data, str):
            # Attempt to extract JSON array if there's text/markdown around it
            s_data = data.strip()
            
            # Remove markdown JSON blocks if present
            if s_data.startswith("```json"):
                s_data = s_data[7:]
            if s_data.startswith("```"):
                s_data = s_data[3:]
            if s_data.endswith("```"):
                s_data = s_data[:-3]
                
            # Find the start of the JSON array
            start_idx = s_data.find('[')
            end_idx = s_data.rfind(']')
            
            if start_idx != -1 and end_idx != -1:
                s_data = s_data[start_idx:end_idx+1]
                
            try:
                data = json.loads(s_data)
            except json.JSONDecodeError as jde:
                logger.warning(f"viz: Failed to parse as JSON, trying literal_eval: {jde}")
                try:
                    import ast
                    data = ast.literal_eval(s_data)
                except Exception as e:
                    logger.error(f"viz: Failed to parse data string completely: {s_data[:100]}... Error: {e}")
                    return None
                
        if not isinstance(data, list):
            logger.error(f"viz: Expected 'data' to be a list, got {type(data)}")
            return None

        df = pd.DataFrame(data)
        
        # Ensure columns exist
        if x_col not in df.columns or y_col not in df.columns:
            logger.error(f"viz: Missing columns {x_col} or {y_col} in data. Available: {list(df.columns)}")
            return None

        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#ffffff')
        
        # Modern color palette
        bar_colors = ['#6366f1', '#8b5cf6', '#d946ef', '#f43f5e', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#0ea5e9']
        
        if chart_type == "bar":
            bars = ax.bar(df[x_col].astype(str), df[y_col].astype(float), color='#6366f1', alpha=0.9, edgecolor='none')
            # Add value labels
            for bar in bars:
                yval = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2, yval + (yval * 0.02), f"{yval:,.0f}", 
                        ha='center', va='bottom', fontsize=10, color='#1f2937', fontweight='bold', fontproperties=prop_bold)
        elif chart_type == "line":
            ax.plot(df[x_col].astype(str), df[y_col].astype(float), marker='o', linewidth=3, markersize=8, color='#10b981')
            # Fill under the line
            ax.fill_between(df[x_col].astype(str), df[y_col].astype(float), color='#10b981', alpha=0.15)
            # Add value labels for points
            for i, txt in enumerate(df[y_col].astype(float)):
                ax.annotate(f"{txt:,.0f}", (df[x_col].astype(str).iloc[i], txt), 
                            textcoords="offset points", xytext=(0,12), ha='center', fontsize=10, color='#1f2937', 
                            fontweight='bold', fontproperties=prop_bold)
        elif chart_type == "pie":
            patches, texts, autotexts = ax.pie(df[y_col].astype(float), labels=df[x_col].astype(str), autopct='%1.1f%%', 
                   startangle=140, colors=bar_colors, wedgeprops={'edgecolor': '#ffffff', 'linewidth': 2}, textprops={'color': '#1f2937'})
            for text in texts:
                text.set_fontproperties(prop_reg)
            for autotext in autotexts:
                autotext.set_fontproperties(prop_bold)
            ax.axis('equal')
        
        # Premium styling
        ax.set_title(title, fontsize=18, fontweight='bold', pad=25, color='#1f2937', fontproperties=prop_bold)
        if chart_type != "pie":
            ax.set_ylabel(y_col.replace('_', ' ').title(), fontsize=12, color='#4b5563', labelpad=15, fontproperties=prop_reg)
            ax.set_xlabel(x_col.replace('_', ' ').title(), fontsize=12, color='#4b5563', labelpad=15, fontproperties=prop_reg)
            
            # Set tick labels font
            for label in ax.get_xticklabels():
                label.set_fontproperties(prop_reg)
                label.set_fontsize(11)
                label.set_color('#374151')
                label.set_rotation(45)
            
            for label in ax.get_yticklabels():
                label.set_fontproperties(prop_reg)
                label.set_fontsize(11)
                label.set_color('#374151')

            ax.grid(axis='y', linestyle='--', alpha=0.5, color='#e5e7eb')
            ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#d1d5db')
            ax.spines['bottom'].set_color('#d1d5db')

        fig.tight_layout()
        
        filename = f"chart_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(CHART_DIR, filename)
        plt.savefig(filepath)
        plt.close()
        
        logger.info(f"viz: Chart generated at {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"viz: Failed to generate chart: {e}")
        return None
