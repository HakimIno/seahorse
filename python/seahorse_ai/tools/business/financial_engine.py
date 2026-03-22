"""seahorse_ai.tools.business.financial_engine — Tools for advanced financial and strategic calculations."""

from __future__ import annotations

import logging
from typing import Dict, Any

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


@tool(
    "Calculate the Break-Even Point (BEP) in units and revenue. "
    "Input the fixed_costs, variable_cost_per_unit, and price_per_unit."
)
async def calculate_break_even(fixed_costs: float, variable_cost_per_unit: float, price_per_unit: float) -> str:
    """Calculates the break-even point."""
    logger.info("calculate_break_even: fixed_costs=%f, vc=%f, price=%f", fixed_costs, variable_cost_per_unit, price_per_unit)
    
    if price_per_unit <= variable_cost_per_unit:
        return "Error: Price per unit must be greater than variable cost per unit to achieve break-even."
        
    contribution_margin_per_unit = price_per_unit - variable_cost_per_unit
    break_even_units = fixed_costs / contribution_margin_per_unit
    break_even_revenue = break_even_units * price_per_unit
    
    return (
        f"### Break-Even Analysis\n"
        f"- **Break-Even Units:** {break_even_units:,.2f} units\n"
        f"- **Break-Even Revenue:** {break_even_revenue:,.2f} \n"
        f"- **Contribution Margin per Unit:** {contribution_margin_per_unit:,.2f} \n"
        f"*(Formula: Fixed Costs / (Price - Variable Cost))*"
    )


@tool(
    "Perform a quick Scenario Analysis (Best Case, Base Case, Worst Case) for a strategic initiative. "
    "Provide the base_revenue, expected_growth_rate (e.g. 0.1 for 10%), base_margin (e.g. 0.3 for 30%), "
    "and variance_pct (e.g. 0.05 for +/- 5% variance in both directions)."
)
async def scenario_analysis(base_revenue: float, expected_growth_rate: float, base_margin: float, variance_pct: float) -> str:
    """Calculates best, base, and worst case scenarios."""
    logger.info("scenario_analysis: base_rev=%f, growth=%f", base_revenue, expected_growth_rate)
    
    # Base Case
    base_proj_rev = base_revenue * (1 + expected_growth_rate)
    base_proj_profit = base_proj_rev * base_margin
    
    # Best Case (+ variance to growth and margin)
    best_proj_rev = base_revenue * (1 + expected_growth_rate + variance_pct)
    best_proj_profit = best_proj_rev * min(1.0, base_margin + variance_pct)
    
    # Worst Case (- variance to growth and margin)
    worst_proj_rev = base_revenue * (1 + expected_growth_rate - variance_pct)
    worst_proj_profit = worst_proj_rev * max(0.0, base_margin - variance_pct)
    
    return (
        f"### Scenario Analysis Outlook\n\n"
        f"**Best Case Scenario (+{variance_pct*100}% variance):**\n"
        f"- Projected Revenue: {best_proj_rev:,.2f}\n"
        f"- Projected Profit: {best_proj_profit:,.2f}\n\n"
        f"**Base Case Scenario:**\n"
        f"- Projected Revenue: {base_proj_rev:,.2f}\n"
        f"- Projected Profit: {base_proj_profit:,.2f}\n\n"
        f"**Worst Case Scenario (-{variance_pct*100}% variance):**\n"
        f"- Projected Revenue: {worst_proj_rev:,.2f}\n"
        f"- Projected Profit: {worst_proj_profit:,.2f}\n\n"
        f"*Ensure fallback strategies (contingencies) address the Worst Case Scenario profit gap.*"
    )

@tool(
    "Calculate the potential financial impact of a promotion or discount. "
    "Input: base_revenue (float), discount_percent (0-100), "
    "predicted_volume_boost_percent (float - e.g., 20.0 for 20% increase). "
    "Output: Predicted new revenue, revenue change, and breakeven notes."
)
async def calculate_promo_impact(
    base_revenue: float, discount_percent: float, predicted_volume_boost_percent: float
) -> str:
    """Predicts ROI of a marketing activity."""
    try:
        discount_factor = (100 - discount_percent) / 100
        boost_factor = (100 + predicted_volume_boost_percent) / 100

        new_revenue = base_revenue * discount_factor * boost_factor
        revenue_change = new_revenue - base_revenue

        # Calculate breakeven boost needed
        breakeven_boost = (1 / discount_factor - 1) * 100 if discount_factor > 0 else 0

        result = [
            "### Promotion Impact Analysis",
            f"- **Original Revenue:** {base_revenue:,.2f}",
            f"- **Discount Applied:** {discount_percent}%",
            f"- **Predicted New Revenue:** {new_revenue:,.2f}",
            f"- **Revenue Delta:** {revenue_change:,.2f} ({(revenue_change / base_revenue * 100) if base_revenue else 0:+.1f}%)",
            f"- **Breakeven Point:** You need at least a {breakeven_boost:.1f}% increase in volume to maintain revenue.",
        ]

        if revenue_change < 0:
            result.append("\n> [!WARNING]\n> This discount might decrease total revenue unless volume boost is higher.")

        return "\n".join(result)
    except Exception as e:
        logger.error("calculate_promo_impact error: %s", e)
        return f"Error in calculation: {e}"


@tool(
    "Calculate profit margin and gross profit. Input: price (float), cost (float), quantity (int)."
)
async def calculate_margin(price: float, cost: float, quantity: int = 1) -> str:
    """Calculate basic unit economics."""
    try:
        revenue = price * quantity
        total_cost = cost * quantity
        profit = revenue - total_cost
        margin_percent = (profit / revenue * 100) if revenue > 0 else 0

        return (
            f"### Margin Analysis\n"
            f"- **Revenue:** {revenue:,.2f}\n"
            f"- **Total Cost:** {total_cost:,.2f}\n"
            f"- **Gross Profit:** {profit:,.2f}\n"
            f"- **Margin:** {margin_percent:.1f}%"
        )
    except Exception as e:
        return f"Error: {e}"
