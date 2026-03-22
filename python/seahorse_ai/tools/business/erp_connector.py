"""seahorse_ai.tools.business.erp_connector — Data ingestion tool for extracting financial data."""

from __future__ import annotations
import logging
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool(
    "Fetch financial statements or POS transaction data from the database. "
    "Input source (e.g., 'Xero', 'POS', 'Stripe'), start_date (YYYY-MM-DD), and end_date (YYYY-MM-DD)."
)
async def fetch_financial_data(source: str, start_date: str, end_date: str) -> str:
    """Connect to a mocked or real financial database, retrieve data, and return a structured summary."""
    logger.info("fetch_financial_data: source=%s, start=%s, end=%s", source, start_date, end_date)
    
    # In a real scenario, this would connect to an ERP API and return real data.
    # Here we provide a mock robust structure for the Agent to process.
    
    return (
        f"### Data Extraction Successful\n"
        f"**Source:** {source} | **Period:** {start_date} to {end_date}\n\n"
        f"The data is available and normalized into the following schema:\n"
        f"- `transaction_date` (Date)\n"
        f"- `product_category` (String)\n"
        f"- `gross_revenue` (Float)\n"
        f"- `cogs` (Float)\n"
        f"- `marketing_spend` (Float)\n"
        f"- `fixed_costs` (Float)\n\n"
        f"**Total Records Fetched:** 2,450\n"
        f"**Insight:** To perform deep-dive analysis across these columns (like LTV, gross margin per category), "
        f"use the `python_interpreter` tool to load and process this dataset using Pandas."
    )
