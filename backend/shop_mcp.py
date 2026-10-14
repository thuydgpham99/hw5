"""The team's connection to the shop, via the MCP server and nothing else.

Every shop fact the agents use comes through here. There is deliberately no second
tools layer: if it is not an MCP tool, no agent can do it.

Two things this module adds on top of the raw server:

1. **Role scoping.** Every agent can read everything -- shared facts are what let a flat
   team work. Writes are scoped to the role that owns them, so the inventory agent cannot
   queue a payment and the accounting agent cannot answer a customer. An agent that needs
   something outside its scope has to ask the teammate who owns it.

2. **A wall around the money.** `decide_approval` and `pay_approved` are never handed to
   any agent. They exist for the human, and the backend calls them on a person's behalf
   through a separate client. An agent cannot approve its own spending request even if it
   decides it would like to.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional, Set

from fastmcp import Client
from fastmcp.client.transports import StdioTransport as FastMCPStdio
from pydantic_ai.mcp import MCPToolset, StdioTransport

from config import REPO_ROOT

SERVER_SCRIPT = REPO_ROOT / "mcp_server" / "server.py"

# Facts. Every agent gets these -- a team that cannot see the same numbers argues instead
# of working.
READ_TOOLS: Set[str] = {
    "get_shop_today",
    "list_tickets",
    "get_ticket",
    "check_stock",
    "list_stock_for_sku",
    "get_sku_margin",
    "get_rent_due",
    "get_cash_balance",
    "list_open_invoices",
    "get_invoice",
    "find_restock_options",
    "list_pending_approvals",
    "list_drafts",
    "list_purchase_orders",
}

# Writes, scoped to the role that owns the consequence.
ROLE_WRITE_TOOLS: Dict[str, Set[str]] = {
    "boss": {"update_ticket_status"},
    "inventory": {"create_purchase_order", "cancel_purchase_order"},
    "accounting": {"request_payment_approval"},
    "facilities": set(),          # rent money is requested by accounting, on request
    "customer_service": {"save_draft_message", "revise_draft"},
}

# The human's half of the loop. Not reachable from any agent toolset.
HUMAN_ONLY_TOOLS: Set[str] = {"decide_approval", "pay_approved"}


def _stdio_args() -> Dict[str, Any]:
    # sys.executable is this backend's interpreter, which already has fastmcp installed.
    return {"command": sys.executable, "args": [str(SERVER_SCRIPT)], "cwd": str(REPO_ROOT)}


def build_shop_toolset() -> MCPToolset:
    """One MCP connection, shared by the whole team for the length of a ticket run.

    Sharing it means one server subprocess per run instead of one per agent, and every
    agent sees the same database state as the others as it changes.
    """
    args = _stdio_args()
    return MCPToolset(
        StdioTransport(command=args["command"], args=args["args"], cwd=args["cwd"]),
        id="campus_customs",
    )


def tools_for_role(role: str) -> Set[str]:
    """The exact tool names one role may call."""
    if role not in ROLE_WRITE_TOOLS:
        raise ValueError(f"Unknown role {role!r}; expected one of {sorted(ROLE_WRITE_TOOLS)}.")
    return READ_TOOLS | ROLE_WRITE_TOOLS[role]


def scoped_toolset(shop: MCPToolset, role: str) -> Any:
    """The shop toolset as one role sees it. Human-only tools are never included."""
    allowed = tools_for_role(role)
    return shop.filtered(lambda ctx, tool_def: tool_def.name in allowed)


# ---------------------------------------------------------------------------------------
# The human path. Called by the backend for a person, never by an agent.
# ---------------------------------------------------------------------------------------


async def call_as_human(tool_name: str, **arguments: Any) -> Any:
    """Call a human-only MCP tool on a person's behalf, over its own short-lived client.

    Refuses anything that is not on the human-only list, so this cannot quietly become a
    general back door into the server.
    """
    if tool_name not in HUMAN_ONLY_TOOLS:
        raise PermissionError(
            f"call_as_human is only for {sorted(HUMAN_ONLY_TOOLS)}; got {tool_name!r}."
        )
    args = _stdio_args()
    transport = FastMCPStdio(command=args["command"], args=args["args"], cwd=args["cwd"])
    async with Client(transport) as client:
        result = await client.call_tool(tool_name, arguments)
        return result.data


async def read_shop(tool_name: str, **arguments: Any) -> Any:
    """Read the shop from the backend itself (for the dashboard), through the same MCP server."""
    if tool_name not in READ_TOOLS:
        raise PermissionError(f"{tool_name!r} is not a read tool.")
    args = _stdio_args()
    transport = FastMCPStdio(command=args["command"], args=args["args"], cwd=args["cwd"])
    async with Client(transport) as client:
        result = await client.call_tool(tool_name, arguments)
        return result.data
