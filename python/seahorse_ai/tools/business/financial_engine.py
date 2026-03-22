"""seahorse_ai.tools.business.financial_engine — Tools for advanced financial and strategic calculations."""

from __future__ import annotations

import logging
from typing import Any

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


@tool(
    "Calculate the Break-Even Point (BEP) in units and revenue. "
    "Input the fixed_costs, variable_cost_per_unit, and price_per_unit. "
    "All monetary values are in Thai Baht (THB)."
)
async def calculate_break_even(
    fixed_costs: float, variable_cost_per_unit: float, price_per_unit: float
) -> dict[str, Any]:
    """Calculates the break-even point with robust error handling and structured return."""
    logger.info(
        "calculate_break_even: fixed_costs=%f, vc=%f, price=%f",
        fixed_costs,
        variable_cost_per_unit,
        price_per_unit,
    )

    try:
        if price_per_unit <= variable_cost_per_unit:
            return {
                "error": "Price per unit must be greater than variable cost per unit to achieve break-even."
            }

        contribution_margin_per_unit = price_per_unit - variable_cost_per_unit
        break_even_units = fixed_costs / contribution_margin_per_unit
        break_even_revenue = break_even_units * price_per_unit

        formatted = (
            f"### Break-Even Analysis\n"
            f"- **Break-Even Units:** {break_even_units:,.2f} units\n"
            f"- **Break-Even Revenue:** {break_even_revenue:,.2f} THB\n"
            f"- **Contribution Margin per Unit:** {contribution_margin_per_unit:,.2f} THB\n"
            f"*(Formula: Fixed Costs / (Price - Variable Cost))*"
        )

        return {
            "break_even_units": break_even_units,
            "break_even_revenue": break_even_revenue,
            "contribution_margin_per_unit": contribution_margin_per_unit,
            "formatted": formatted,
        }
    except (TypeError, ZeroDivisionError) as e:
        logger.error("calculate_break_even error: %s", e)
        return {"error": f"Invalid input types or division by zero: {e}"}
    except Exception as e:
        logger.error("calculate_break_even unexpected error: %s", e)
        return {"error": f"Unexpected error: {e}"}


@tool(
    "Perform a quick Scenario Analysis (Best Case, Base Case, Worst Case) for a strategic initiative. "
    "Provide the base_revenue, expected_growth_rate (e.g. 0.1 for 10%), base_margin (e.g. 0.3 for 30%), "
    "and variance_pct (e.g. 0.05 for +/- 5% variance in both directions). "
    "All monetary values are in Thai Baht (THB)."
)
async def scenario_analysis(
    base_revenue: float,
    expected_growth_rate: float,
    base_margin: float,
    variance_pct: float,
) -> dict[str, Any]:
    """Calculates best, base, and worst case scenarios with clamped growth and structured return."""
    logger.info("scenario_analysis: base_rev=%f, growth=%f", base_revenue, expected_growth_rate)

    try:
        # Base Case
        base_proj_rev = base_revenue * (1 + expected_growth_rate)
        base_proj_profit = base_proj_rev * base_margin

        # Best Case (+ variance to growth and margin)
        best_proj_rev = base_revenue * (1 + expected_growth_rate + variance_pct)
        best_proj_profit = best_proj_rev * min(1.0, base_margin + variance_pct)

        # Worst Case (- variance to growth and margin)
        # Clamp growth at -100% (total business loss)
        worst_growth = max(-1.0, expected_growth_rate - variance_pct)
        worst_proj_rev = base_revenue * (1 + worst_growth)
        worst_proj_profit = worst_proj_rev * max(0.0, base_margin - variance_pct)

        formatted = (
            f"### Scenario Analysis Outlook (THB)\n\n"
            f"**Best Case Scenario (+{variance_pct * 100:g}% variance):**\n"
            f"- Projected Revenue: {best_proj_rev:,.2f}\n"
            f"- Projected Profit: {best_proj_profit:,.2f}\n\n"
            f"**Base Case Scenario:**\n"
            f"- Projected Revenue: {base_proj_rev:,.2f}\n"
            f"- Projected Profit: {base_proj_profit:,.2f}\n\n"
            f"**Worst Case Scenario ({worst_growth * 100:g}% growth):**\n"
            f"- Projected Revenue: {worst_proj_rev:,.2f}\n"
            f"- Projected Profit: {worst_proj_profit:,.2f}\n\n"
            f"*Ensure fallback strategies address the worst-case scenario profit gap.*"
        )

        return {
            "base": {"revenue": base_proj_rev, "profit": base_proj_profit},
            "best": {"revenue": best_proj_rev, "profit": best_proj_profit},
            "worst": {"revenue": worst_proj_rev, "profit": worst_proj_profit},
            "formatted": formatted,
        }
    except TypeError as e:
        logger.error("scenario_analysis type error: %s", e)
        return {"error": f"Invalid input types: {e}"}
    except Exception as e:
        logger.error("scenario_analysis unexpected error: %s", e)
        return {"error": str(e)}


@tool(
    "Calculate the potential financial impact of a promotion or discount. "
    "Input: base_revenue (float), discount_percent (0-100), "
    "predicted_volume_boost_percent (float - e.g., 20.0 for 20% increase). "
    "All monetary values are in Thai Baht (THB)."
)
async def calculate_promo_impact(
    base_revenue: float, discount_percent: float, predicted_volume_boost_percent: float
) -> dict[str, Any]:
    """Predicts ROI of a marketing activity with structured return."""
    try:
        discount_factor = (100 - discount_percent) / 100
        boost_factor = (100 + predicted_volume_boost_percent) / 100

        new_revenue = base_revenue * discount_factor * boost_factor
        revenue_change = new_revenue - base_revenue
        revenue_change_pct = (revenue_change / base_revenue * 100) if base_revenue else 0

        # Calculate breakeven boost needed
        breakeven_boost = (1 / discount_factor - 1) * 100 if discount_factor > 0 else 0

        status_msg = ""
        if revenue_change < 0:
            status_msg = "\n> [!WARNING]\n> This discount might decrease total revenue unless volume boost is higher."

        formatted = (
            f"### Promotion Impact Analysis (THB)\n"
            f"- **Original Revenue:** {base_revenue:,.2f}\n"
            f"- **Discount Applied:** {discount_percent}%\n"
            f"- **Predicted New Revenue:** {new_revenue:,.2f}\n"
            f"- **Revenue Delta:** {revenue_change:,.2f} ({revenue_change_pct:+.1f}%)\n"
            f"- **Breakeven Point:** You need at least a {breakeven_boost:.1f}% increase in volume to maintain revenue."
            f"{status_msg}"
        )

        return {
            "new_revenue": new_revenue,
            "revenue_change": revenue_change,
            "revenue_change_pct": revenue_change_pct,
            "breakeven_volume_boost_pct": breakeven_boost,
            "formatted": formatted,
        }
    except (TypeError, ZeroDivisionError) as e:
        logger.error("calculate_promo_impact error: %s", e)
        return {"error": str(e)}


@tool(
    "Calculate profit margin and gross profit. Input: price (float), cost (float), quantity (int). "
    "All monetary values are in Thai Baht (THB)."
)
async def calculate_margin(price: float, cost: float, quantity: int = 1) -> dict[str, Any]:
    """Calculate basic unit economics with validation and structured return."""
    try:
        if quantity <= 0:
            return {"error": "Quantity must be greater than 0."}

        revenue = price * quantity
        total_cost = cost * quantity
        profit = revenue - total_cost
        margin_percent = (profit / revenue * 100) if revenue > 0 else 0

        formatted = (
            f"### Margin Analysis (THB)\n"
            f"- **Revenue:** {revenue:,.2f}\n"
            f"- **Total Cost:** {total_cost:,.2f}\n"
            f"- **Gross Profit:** {profit:,.2f}\n"
            f"- **Margin:** {margin_percent:.1f}%"
        )

        return {
            "revenue": revenue,
            "total_cost": total_cost,
            "gross_profit": profit,
            "margin_percent": margin_percent,
            "formatted": formatted,
        }
    except TypeError as e:
        return {"error": f"Invalid input types: {e}"}
    except Exception as e:
        return {"error": str(e)}
