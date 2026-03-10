"""seahorse_ai.tools.business_math — Tools for financial and business analysis."""
from __future__ import annotations

import logging

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool(
    "Calculate the potential financial impact of a promotion or discount. "
    "Input: base_revenue (float), discount_percent (0-100), "
    "predicted_volume_boost_percent (float - e.g., 20.0 for 20% increase). "
    "Output: Predicted new revenue, revenue change, and breakeven notes."
)
async def calculate_promo_impact(
    base_revenue: float, 
    discount_percent: float, 
    predicted_volume_boost_percent: float
) -> str:
    """Predicts ROI of a marketing activity."""
    try:
        discount_factor = (100 - discount_percent) / 100
        boost_factor = (100 + predicted_volume_boost_percent) / 100
        
        new_revenue = base_revenue * discount_factor * boost_factor
        revenue_change = new_revenue - base_revenue
        
        # Calculate breakeven boost needed
        # base_rev = (base_rev * discount_factor) * x => x = 1 / discount_factor
        breakeven_boost = (1 / discount_factor - 1) * 100 if discount_factor > 0 else 0
        
        result = [
            "--- Promotion Impact Analysis ---",
            f"Original Revenue: {base_revenue:,.2f}",
            f"Discount Applied: {discount_percent}%",
            f"Predicted New Revenue: {new_revenue:,.2f}",
            f"Revenue Delta: {revenue_change:,.2f} ({ (revenue_change/base_revenue*100) if base_revenue else 0:+.1f}%)",
            f"Breakeven Point: You need at least a {breakeven_boost:.1f}% increase in volume to maintain revenue."
        ]
        
        if revenue_change < 0:
            result.append("\n⚠️ WARNING: This discount might decrease total revenue unless volume boost is higher.")
            
        return "\n".join(result)
    except Exception as e:
        logger.error("calculate_promo_impact error: %s", e)
        return f"Error in calculation: {e}"

@tool(
    "Calculate profit margin and gross profit. "
    "Input: price (float), cost (float), quantity (int)."
)
async def calculate_margin(price: float, cost: float, quantity: int = 1) -> str:
    """Calculate basic unit economics."""
    try:
        revenue = price * quantity
        total_cost = cost * quantity
        profit = revenue - total_cost
        margin_percent = (profit / revenue * 100) if revenue > 0 else 0
        
        return (
            f"--- Margin Analysis ---\n"
            f"Revenue: {revenue:,.2f}\n"
            f"Total Cost: {total_cost:,.2f}\n"
            f"Gross Profit: {profit:,.2f}\n"
            f"Margin: {margin_percent:.1f}%"
        )
    except Exception as e:
        return f"Error: {e}"
