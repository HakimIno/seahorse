"""Table visualization tool — generates premium table images using Playwright."""

from __future__ import annotations

import json
import logging
import os
import uuid

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.system.browser import browser_screenshot

logger = logging.getLogger(__name__)

# Directory for temporary charts/tables
CHART_DIR = "/tmp/seahorse_charts"
os.makedirs(CHART_DIR, exist_ok=True)


@tool(
    "Generate a PREMIUM, high-fidelity image of a data table from JSON. "
    "Use this for datasets with more than 3 rows or columns to ensure beautiful aesthetics in Telegram. "
    "Input: title (string), data_json (string containing a list of dictionaries)."
)
async def create_table_image(
    title: str,
    data_json: str,
) -> str:
    """Render a JSON dataset into a styled PNG table via browser_screenshot."""
    filename = f"table_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(CHART_DIR, filename)
    temp_html = os.path.join(CHART_DIR, f"{filename}.html")

    try:
        # 1. Parse Data
        data = json.loads(data_json)
        if not isinstance(data, list) or not data:
            return "Error: data_json must be a non-empty list of dictionaries."

        headers = list(data[0].keys())

        # 2. Build Premium HTML/CSS Template
        rows_html = ""
        for row in data:
            cells = "".join([f"<td>{row.get(h, '')}</td>" for h in headers])
            rows_html += f"<tr>{cells}</tr>"

        headers_html = "".join([f"<th>{h}</th>" for h in headers])

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600&family=IBM+Plex+Sans+Thai:wght@400;600&display=swap');
                
                body {{
                    font-family: 'Crimson Pro', 'IBM Plex Sans Thai', serif;
                    background: white;
                    margin: 0;
                    padding: 60px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    color: #1a1a1a;
                }}
                .title-container {{
                    width: 100%;
                    max-width: 900px;
                    text-align: center;
                    margin-bottom: 30px;
                }}
                h1 {{
                    font-size: 24px;
                    font-weight: 600;
                    margin: 0;
                    letter-spacing: 0.02em;
                }}
                table {{
                    width: 100%;
                    max-width: 900px;
                    border-collapse: collapse;
                    text-align: left;
                    border-top: 2.5px solid #1a1a1a;
                    border-bottom: 2.5px solid #1a1a1a;
                }}
                th {{
                    padding: 12px 15px;
                    font-size: 16px;
                    font-weight: 600;
                    border-bottom: 1.5px solid #1a1a1a;
                    background: white;
                    color: #000;
                }}
                td {{
                    padding: 12px 15px;
                    font-size: 16px;
                    color: #333;
                    border-bottom: 0.5px solid #e5e5e5;
                }}
                tr:last-child td {{
                    border-bottom: none;
                }}
                /* Booktabs style: no vertical lines, minimal horizontal lines */
            </style>
        </head>
        <body>
            <div class="title-container">
                <h1>{title}</h1>
            </div>
            <table>
                <thead>
                    <tr>{headers_html}</tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </body>
        </html>
        """

        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_content)

        # 3. Render via Playwright
        await browser_screenshot(url=f"file://{os.path.abspath(temp_html)}", output_path=filepath)

        if os.path.exists(temp_html):
            os.remove(temp_html)

        logger.info(f"table_viz: Premium table image generated at {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"table_viz: Failed to generate table image: {e}")
        return f"Error: Table image generation failed: {e}"
