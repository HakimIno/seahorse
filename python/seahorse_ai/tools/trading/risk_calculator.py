import math
from typing import Any

from seahorse_ai.tools.base import tool


@tool(
    "Calculate the exact Lot Size to trade to ensure the risk does not exceed the allowed percentage."
)
async def calculate_position_size(
    account_balance: float,
    risk_percentage: float,
    stop_loss_pips: float,
    pip_value_per_lot: float = 10.0,
) -> dict[str, Any]:
    """Calculate the exact Lot Size to trade to ensure the risk does not exceed the allowed percentage.
    Inputs:
    - account_balance: Total account size (e.g., 1000)
    - risk_percentage: % of account to risk (e.g., 1.0 for 1%)
    - stop_loss_pips: Stop loss distance in pips (e.g., 20)
    - pip_value_per_lot: Dollar value of 1 pip for 1 Standard Lot (default 10.0 for EURUSD).
    """
    try:
        if account_balance <= 0 or stop_loss_pips <= 0 or pip_value_per_lot <= 0:
            return {
                "error": "Account balance, stop loss pips, and pip value must be greater than 0."
            }
        if risk_percentage <= 0 or risk_percentage > 100:
            return {"error": "Risk percentage must be between 0 and 100."}

        risk_amount = account_balance * (risk_percentage / 100)
        lot_size = risk_amount / (stop_loss_pips * pip_value_per_lot)

        return {
            "account_balance": account_balance,
            "risk_percentage_used": risk_percentage,
            "max_loss_amount": round(risk_amount, 2),
            "stop_loss_pips": stop_loss_pips,
            "recommended_lot_size": round(lot_size, 2),
        }
    except Exception as e:
        return {"error": f"Invalid calculation: {e}"}


@tool("Suggests optimal bet sizing for long-term compound growth based on historical performance.")
async def evaluate_kelly_criterion(win_rate: float, risk_reward_ratio: float) -> dict[str, Any]:
    """Suggests optimal bet sizing for long-term compound growth based on historical performance.
    Inputs:
    - win_rate: Probability of winning (e.g., 0.45 for 45%)
    - risk_reward_ratio: Average win size divided by average loss size (e.g., 2.0 for 1:2 R:R)
    """
    try:
        if not (0 < win_rate < 1):
            return {"error": "Win rate must be a float between 0 and 1 (e.g., 0.45)."}
        if risk_reward_ratio <= 0:
            return {"error": "Risk:Reward ratio must be > 0."}

        loss_rate = 1.0 - win_rate
        # Kelly % = W - [(1 - W) / R]
        kelly_percentage = win_rate - (loss_rate / risk_reward_ratio)

        fractional_kelly = kelly_percentage / 2.0  # Half-Kelly is safer for trading

        summary = "No edge. Do not trade." if kelly_percentage <= 0 else "Positive expectancy."

        return {
            "win_rate": f"{win_rate * 100}%",
            "risk_reward": f"1:{risk_reward_ratio}",
            "full_kelly": f"{round(kelly_percentage * 100, 2)}%" if kelly_percentage > 0 else "0%",
            "half_kelly_safe_risk": f"{round(fractional_kelly * 100, 2)}%"
            if kelly_percentage > 0
            else "0%",
            "advice": summary,
        }
    except Exception as e:
        return {"error": str(e)}


@tool("Calculates the probability of losing 50% of the account (ruin threshold).")
async def calculate_risk_of_ruin(
    win_rate: float, risk_reward_ratio: float, risk_per_trade_percent: float
) -> dict[str, Any]:
    """Calculates the probability of losing 50% of the account (ruin threshold) given the current stats."""
    try:
        if not (0 < win_rate < 1):
            return {"error": "Win rate must be a float between 0 and 1 (e.g., 0.45)."}

        risk_fraction = risk_per_trade_percent / 100.0

        if risk_fraction >= 1.0:
            return {
                "probability_of_50_percent_loss": "100%",
                "advice": "Guaranteed ruin. Risk is too high.",
            }

        # Simplified Random Walk approximation for hitting -50% boundary
        # If expectancy is negative, ruin is 100%
        expectancy = (win_rate * risk_reward_ratio) - (1.0 - win_rate)
        if expectancy <= 0:
            return {
                "expectancy": round(expectancy, 2),
                "probability_of_50_percent_loss": "100%",
                "advice": "System has negative expectancy. You will eventually go broke regardless of risk size.",
            }

        # Use an approximation formula: ROR = e^(-2 * Expectancy * Account_Units / Variance)
        # We simplify for educational purposes to show how high risk scales probability of ruin
        # A simpler version: Risk of Ruin = ((1 - Edge) / (1 + Edge)) ^ Units
        edge = expectancy
        units = 0.5 / risk_fraction  # Number of losing trades to lose 50%

        if edge >= 1:
            ror_pct = 0.0
        else:
            base = (1.0 - edge) / (1.0 + edge)
            ror = math.pow(base, units)
            ror_pct = min(100.0, ror * 100.0)

        return {
            "win_rate": f"{win_rate * 100}%",
            "risk_reward": risk_reward_ratio,
            "risk_per_trade": f"{risk_per_trade_percent}%",
            "probability_of_losing_half_account": f"{round(ror_pct, 2)}%",
            "advice": "High risk!" if ror_pct > 20 else "Risk is manageable.",
        }
    except Exception as e:
        return {"error": str(e)}
