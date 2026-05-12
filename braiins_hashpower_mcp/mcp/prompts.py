"""MCP prompts for reusable agent workflows."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Attach all Braiins prompts to a FastMCP instance."""

    @mcp.prompt()
    def place_conservative_bid() -> str:
        """Guided workflow for placing a conservative spot bid."""
        return (
            "You are helping a user place a conservative bid on Braiins Hashpower.\n"
            "\n"
            "Follow these steps in order:\n"
            "1. Call `get_market_settings` and explain the price and hashrate units to the user.\n"
            "2. Call `get_orderbook` with depth=10 and show the top 5 levels.\n"
            "3. Suggest a bid price that is 1-2% below the current best ask.\n"
            "4. Call `create_bid` with dry_run=true using the suggested values.\n"
            "5. Present the preview to the user and ask for explicit confirmation.\n"
            "6. Only call `create_bid` with dry_run=false after the user confirms.\n"
        )

    @mcp.prompt()
    def review_open_orders() -> str:
        """Summarize open order exposure and recommend actions without mutating state."""
        return (
            "Review the user's current open orders on Braiins Hashpower.\n"
            "\n"
            "Steps:\n"
            "1. Call `get_market_settings` to get current unit context.\n"
            "2. Call `list_orders` with status=['open'].\n"
            "3. Call `get_orderbook` to compare open bid prices against current market.\n"
            "4. Summarize: number of open bids, total exposure, distance from best ask.\n"
            "5. Recommend actions (e.g., cancel stale bids, adjust prices) but do NOT\n"
            "   execute any changes without explicit user instruction.\n"
        )

    @mcp.prompt()
    def explain_price_units() -> str:
        """Explain how price and hashrate units work on Braiins Hashpower."""
        return (
            "Explain how price and hashrate units work on the Braiins Hashpower spot market.\n"
            "\n"
            "1. Call `get_market_settings` to retrieve the current units.\n"
            "2. Explain `price_sat` (price per unit of hashrate, in satoshi).\n"
            "3. Explain `hr_unit` (the denomination of hashrate being traded, e.g. EH/day).\n"
            "4. Give a concrete example: 'At price_sat=100 and hr_unit=EH/day, buying 2 EH/day\n"
            "   costs 200 satoshi per day.'\n"
            "5. Warn the user to always verify units before placing bids, as they may change.\n"
        )
