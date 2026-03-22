"""seahorse_ai.tools.business.forecaster — Predictive analytics for Seahorse AI."""

import logging
from typing import Any

import numpy as np

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


@tool(
    "Predicts future sales based on historical data using linear regression. "
    "Requires a list of dictionaries with 'date' and 'revenue' keys, and an optional days_to_forecast integer."
)
def forecast_sales(history: list[dict[str, Any]], days_to_forecast: int = 7) -> dict[str, Any]:
    """Predicts future sales based on historical data using linear regression.

    Args:
        history: List of dictionaries with 'date' and 'revenue' keys.
        days_to_forecast: Number of days to predict into the future.

    Returns:
        A dictionary containing the forecast and confidence metrics.

    """
    if not history:
        return {"error": "History data is empty."}

    # Handle cases where history might be a JSON-encoded string
    if isinstance(history, str):
        try:
            import json

            history = json.loads(history)
        except Exception:
            return {"error": "Failed to parse history JSON string."}

    if not isinstance(history, list):
        return {"error": f"Invalid history format: expected list, got {type(history).__name__}"}

    if len(history) < 3:
        return {"error": "Insufficient data for forecasting (need at least 3 days)."}

    try:
        # Extract y (revenue) safely
        y_vals = []
        for h in history:
            if not isinstance(h, dict):
                # If it's a list, maybe [date, value]?
                if isinstance(h, (list, tuple)) and len(h) >= 2:
                    y_vals.append(float(h[1]))
                continue

            # Try various keys
            val = h.get("revenue") or h.get("value") or h.get("amount") or h.get("total")
            if val is not None:
                y_vals.append(float(val))

        if len(y_vals) < 3:
            return {"error": "Could not extract sufficient revenue data points from history."}

        y = np.array(y_vals)
        x = np.arange(len(y))

        # Simple linear regression: y = mx + c
        m, c = np.polyfit(x, y, 1)

        # Forecast future points
        future_x = np.arange(len(y), len(y) + days_to_forecast)
        forecast_y = m * future_x + c

        # Ensure no negative revenue in forecast
        forecast_y = np.maximum(forecast_y, 0)

        # Calculate daily average Growth Rate
        # (Current - Start) / Start
        start_val = max(y[0], 1)
        (y[-1] - y[0]) / start_val

        # Calculate R-squared (simple confidence metric)
        y_pred = m * x + c
        r_squared = 1 - (np.sum((y - y_pred) ** 2) / np.sum((y - np.mean(y)) ** 2))

        return {
            "forecast": [
                {"day": i + 1, "predicted_revenue": round(val, 2)}
                for i, val in enumerate(forecast_y)
            ],
            "total_predicted_revenue": round(float(np.sum(forecast_y)), 2),
            "trend_slope": round(float(m), 2),
            "confidence_score": round(float(max(0, r_squared)), 2),
            "is_growing": m > 0,
            "summary": f"Based on last {len(history)} days, the business is {'growing' if m > 0 else 'declining'} at a rate of {abs(m):.2f} units/day.",
        }

    except Exception as e:
        logger.error(f"forecaster: Prediction failed: {e}")
        return {"error": f"Forecasting error: {str(e)}"}
