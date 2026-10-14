"""Campus Customs MCP server.

The single door between the Campus Customs agent team and the shop's data. Every agent
(boss, inventory, accounting, facilities, customer service) reads and writes the shop
through these tools; there is no second shop-tools layer that bypasses MCP.

The server talks ONLY to the working copy, data/campus_customs_new.db. The original
data/campus_customs.db is never opened here -- it stays pristine so a run can be reset.

Rules enforced in this layer, so no agent can route around them:
  * desk.date_today is "today". Overdue and ETA math uses it, never the wall clock.
  * A vendor with an open unpaid invoice will not ship -- create_purchase_order refuses.
  * Money only moves through an approval a human decided. pay_approved refuses anything
    that is not status='approved', and refuses to overdraw the account.
  * Amounts are never taken on an agent's word: a payment request must match the invoice,
    lease, or purchase order it points at.
  * Tools never invent data. Every value is read from a table or computed from values read
    from tables; a missing row comes back as {"found": false}.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

# --------------------------------------------------------------------------------------
# Database wiring
# --------------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "campus_customs_new.db"

# Override for tests; defaults to the working copy. Never point this at campus_customs.db.
DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB", DEFAULT_DB_PATH))

mcp = FastMCP("campus-customs")

# Work the agents produce that the original schema has nowhere to put. These live in the
# working copy only, so resetting the run (re-copying the original) clears them too.
WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY,
    ticket_id   INTEGER NOT NULL,
    audience    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    drafted_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    revision    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY,
    ticket_id     INTEGER,
    kind          TEXT NOT NULL,     -- invoice | rent | purchase_order
    ref_id        INTEGER,           -- invoices.id | leases.id | purchase_orders.id
    amount        REAL NOT NULL,
    account       TEXT NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL,     -- pending | approved | denied | paid
    requested_by  TEXT NOT NULL,
    requested_at  TEXT NOT NULL,
    decided_by    TEXT,
    decided_at    TEXT,
    payment_id    INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id               INTEGER PRIMARY KEY,
    ticket_id        INTEGER,
    vendor_id        INTEGER NOT NULL,
    sku              TEXT NOT NULL,
    size             TEXT NOT NULL,
    qty              INTEGER NOT NULL,
    unit_cost        REAL NOT NULL,
    total_cost       REAL NOT NULL,
    status           TEXT NOT NULL,  -- draft_pending_approval | ordered | cancelled
    expected_arrival TEXT,
    created_by       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
"""


def _connect(write: bool = False) -> sqlite3.Connection:
    """Open the working-copy database. Reads get a read-only handle."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Working database not found at {DB_PATH}. "
            "Create it with: cp data/campus_customs.db data/campus_customs_new.db"
        )
    uri = f"file:{DB_PATH}" + ("" if write else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_workspace_tables() -> None:
    """Create the drafts/approvals/purchase_orders tables if this working copy is fresh."""
    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        # Added after the first run: lets a draft be revised in place rather than
        # duplicated. Guarded so an existing working copy migrates instead of breaking.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(drafts)")}
        if "revision" not in cols:
            conn.execute("ALTER TABLE drafts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")


def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _today() -> str:
    """The shop's 'today' from desk.date_today -- not the real wall-clock date."""
    row = _one("SELECT date_today FROM desk LIMIT 1")
    if row is None:
        raise RuntimeError("desk table is empty: the shop has no date_today")
    return row["date_today"]


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _add_days(start: str, days: int) -> str:
    return date.fromordinal(date.fromisoformat(start).toordinal() + days).isoformat()


def _add_one_month(start: str) -> str:
    """Advance a due date by one month, clamping the day if the next month is shorter."""
    d = date.fromisoformat(start)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    day = d.day
    while day > 1:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            day -= 1
    return date(year, month, 1).isoformat()


try:  # A fresh working copy needs its workspace tables before any tool runs.
    _ensure_workspace_tables()
except Exception:  # pragma: no cover - surfaced by the first tool call instead
    pass


# ======================================================================================
# READ TOOLS -- the board and the shop's state
# ======================================================================================


@mcp.tool()
def get_shop_today() -> Dict[str, Any]:
    """Get the shop's current date from desk.date_today. Use this for every overdue or ETA
    calculation -- the real calendar date is not the shop's date."""
    row = _one("SELECT date_today, notes FROM desk LIMIT 1")
    return {"found": row is not None, **(row or {})}


@mcp.tool()
def list_tickets(status: Optional[str] = None) -> Dict[str, Any]:
    """List tickets on the board, newest first. Pass status='open' for unresolved work.

    Reads the tickets table. Each ticket carries the keys that say who should handle it:
    sku/size/qty for product work, lease_id for space work, invoice_id for a bill.
    """
    sql = (
        "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, "
        "status, notes, created_at FROM tickets"
    )
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC"
    tickets = _rows(sql, params)
    return {"count": len(tickets), "shop_today": _today(), "tickets": tickets}


@mcp.tool()
def get_ticket(ticket_id: int) -> Dict[str, Any]:
    """Get one ticket by id, with the linked lease/invoice rows resolved.

    Reads tickets, plus leases and invoices for whatever the ticket points at, so the
    handling agent sees the real amount and date rather than the requester's description.
    """
    ticket = _one(
        "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, "
        "status, notes, created_at FROM tickets WHERE id = ?",
        (ticket_id,),
    )
    if ticket is None:
        return {"found": False, "ticket_id": ticket_id, "message": f"No ticket {ticket_id}."}

    result: Dict[str, Any] = {"found": True, "shop_today": _today(), "ticket": ticket}
    if ticket["lease_id"] is not None:
        result["linked_lease"] = _one(
            "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases WHERE id = ?",
            (ticket["lease_id"],),
        )
    if ticket["invoice_id"] is not None:
        result["linked_invoice"] = _one(
            "SELECT i.id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, "
            "i.status, i.description FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
            "WHERE i.id = ?",
            (ticket["invoice_id"],),
        )
    return result


@mcp.tool()
def check_stock(sku: str, size: str, qty_needed: Optional[int] = None) -> Dict[str, Any]:
    """Check on-hand units for one SKU in one size, and the shortfall against a requested qty.

    Reads inventory, which is keyed on (sku, size) -- a SKU that looks well stocked overall
    can still be at zero in the size a customer asked for, so both arguments are required.
    """
    row = _one(
        "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
        (sku, size),
    )
    if row is None:
        return {
            "found": False,
            "sku": sku,
            "size": size,
            "message": f"No inventory row for sku={sku} size={size}.",
        }

    on_hand = row["qty"]
    result: Dict[str, Any] = {
        "found": True,
        "sku": row["sku"],
        "name": row["name"],
        "size": row["size"],
        "qty_on_hand": on_hand,
        "location": row["location"],
    }
    if qty_needed is not None:
        shortfall = max(0, qty_needed - on_hand)
        result.update(
            {"qty_needed": qty_needed, "can_fill_now": shortfall == 0, "shortfall": shortfall}
        )
    return result


@mcp.tool()
def list_stock_for_sku(sku: str) -> Dict[str, Any]:
    """List every size of one SKU with its on-hand qty. Use it to see whether a shortfall is
    one bad size or the whole product. Reads inventory."""
    rows = _rows(
        "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? ORDER BY size",
        (sku,),
    )
    return {
        "found": bool(rows),
        "sku": sku,
        "sizes": rows,
        "total_units": sum(r["qty"] for r in rows),
    }


@mcp.tool()
def get_sku_margin(
    sku: str,
    qty: Optional[int] = None,
    proposed_unit_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Get unit cost, list price, and the margin room on a SKU -- the floor for a discount.

    Reads pricing, which is keyed on sku alone and has no size column, so cost and list
    price are the same across sizes. Pass proposed_unit_price to test a specific discount.
    """
    row = _one("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,))
    if row is None:
        return {"found": False, "sku": sku, "message": f"No pricing row for sku={sku}."}

    unit_cost, list_price = row["unit_cost"], row["list_price"]
    unit_margin = list_price - unit_cost
    pct = round(100.0 * unit_margin / list_price, 2) if list_price else None

    result: Dict[str, Any] = {
        "found": True,
        "sku": row["sku"],
        "unit_cost": unit_cost,
        "list_price": list_price,
        "unit_margin": unit_margin,
        "margin_pct_of_list": pct,
        "max_discount_pct_before_loss": pct,
        "break_even_unit_price": unit_cost,
    }
    if qty is not None:
        result.update(
            {
                "qty": qty,
                "revenue_at_list": round(list_price * qty, 2),
                "cost_at_qty": round(unit_cost * qty, 2),
                "margin_at_list": round(unit_margin * qty, 2),
            }
        )
    if proposed_unit_price is not None:
        proposed_margin = proposed_unit_price - unit_cost
        result.update(
            {
                "proposed_unit_price": proposed_unit_price,
                "proposed_unit_margin": round(proposed_margin, 2),
                "proposed_discount_pct": (
                    round(100.0 * (list_price - proposed_unit_price) / list_price, 2)
                    if list_price
                    else None
                ),
                "proposed_is_above_cost": proposed_margin > 0,
            }
        )
        if qty is not None:
            result["proposed_total_margin"] = round(proposed_margin * qty, 2)
    return result


@mcp.tool()
def get_rent_due(lease_id: int) -> Dict[str, Any]:
    """Get the rent amount and due date for one lease, dated against the shop's today.

    Reads leases for the lease row and desk for today. Rent tickets carry only a lease_id,
    so the amount owed has to come from the lease rather than from the ticket text.
    """
    row = _one(
        "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
        (lease_id,),
    )
    if row is None:
        return {"found": False, "lease_id": lease_id, "message": f"No lease with id={lease_id}."}

    today = _today()
    days = _days_between(today, row["next_due"])
    return {
        "found": True,
        "lease_id": row["id"],
        "space_name": row["space_name"],
        "landlord": row["landlord"],
        "monthly_rent": row["monthly_rent"],
        "next_due": row["next_due"],
        "notes": row["notes"],
        "shop_today": today,
        "days_until_due": days,
        "is_overdue": days < 0,
    }


@mcp.tool()
def get_cash_balance(account: str = "checking") -> Dict[str, Any]:
    """Get the balance of a cash account. No revenue comes in during this run, so this only
    ever goes down -- treat it as the hard ceiling on everything the team approves.
    Reads cash_accounts."""
    row = _one("SELECT name, balance, date FROM cash_accounts WHERE name = ?", (account,))
    if row is None:
        return {"found": False, "account": account, "message": f"No cash account '{account}'."}
    return {"found": True, **row, "shop_today": _today()}


@mcp.tool()
def list_open_invoices() -> Dict[str, Any]:
    """List unpaid invoices with their vendor and how overdue each one is.

    Reads invoices joined to vendors, dated against desk.date_today. An open invoice is a
    shipping blocker as well as a bill: its vendor will not ship new product until it clears.
    """
    today = _today()
    rows = _rows(
        "SELECT i.id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, i.status, "
        "i.description FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
        "WHERE i.status != 'paid' ORDER BY i.due_date"
    )
    for r in rows:
        overdue_by = -_days_between(today, r["due_date"])
        r["days_overdue"] = max(0, overdue_by)
        r["is_overdue"] = overdue_by > 0
    return {
        "count": len(rows),
        "shop_today": today,
        "total_owed": round(sum(r["amount"] for r in rows), 2),
        "invoices": rows,
    }


@mcp.tool()
def get_invoice(invoice_id: int) -> Dict[str, Any]:
    """Get one invoice with its vendor and overdue status. Reads invoices joined to vendors."""
    row = _one(
        "SELECT i.id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, i.status, "
        "i.description FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
        (invoice_id,),
    )
    if row is None:
        return {"found": False, "invoice_id": invoice_id, "message": f"No invoice {invoice_id}."}
    today = _today()
    overdue_by = -_days_between(today, row["due_date"])
    return {
        "found": True,
        **row,
        "shop_today": today,
        "days_overdue": max(0, overdue_by),
        "is_overdue": overdue_by > 0,
    }


@mcp.tool()
def find_restock_options(sku: Optional[str] = None) -> Dict[str, Any]:
    """List every vendor with their specialty, lead time, arrival date, and whether an unpaid
    invoice is blocking them from shipping.

    Reads vendors and invoices, dated from desk.date_today. can_ship_now is False whenever the
    vendor has an open invoice -- that vendor ships nothing new until it is paid. Pass a sku to
    get its unit cost from pricing alongside each option. Match the specialty text to the
    product yourself; this tool reports what the tables say and does not guess a mapping.
    """
    today = _today()
    vendors = _rows("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id")
    blockers = _rows(
        "SELECT id, vendor_id, amount, due_date, status FROM invoices WHERE status != 'paid'"
    )
    for v in vendors:
        mine = [b for b in blockers if b["vendor_id"] == v["id"]]
        v["blocking_invoices"] = mine
        v["can_ship_now"] = not mine
        v["earliest_arrival_if_ordered_today"] = _add_days(today, v["lead_days"])
        if mine:
            v["blocked_reason"] = (
                f"{v['name']} has {len(mine)} unpaid invoice(s) totalling "
                f"{round(sum(b['amount'] for b in mine), 2)}; they will not ship until paid."
            )
    result: Dict[str, Any] = {"shop_today": today, "vendors": vendors}
    if sku:
        price = _one("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,))
        result["sku"] = sku
        result["pricing"] = price
    return result


@mcp.tool()
def list_pending_approvals() -> Dict[str, Any]:
    """List payment approval requests and where each one stands (pending, approved, denied,
    paid). Reads approvals. Agents can read this queue but only a human decides it."""
    rows = _rows("SELECT * FROM approvals ORDER BY id")
    return {
        "count": len(rows),
        "pending_count": sum(1 for r in rows if r["status"] == "pending"),
        "approvals": rows,
    }


@mcp.tool()
def list_drafts(ticket_id: Optional[int] = None) -> Dict[str, Any]:
    """List customer/vendor message drafts sitting on the board. Reads drafts. Drafts are never
    sent from here -- a human sends them."""
    sql, params = "SELECT * FROM drafts", ()
    if ticket_id is not None:
        sql, params = sql + " WHERE ticket_id = ?", (ticket_id,)
    rows = _rows(sql + " ORDER BY id", params)
    return {"count": len(rows), "drafts": rows}


@mcp.tool()
def list_purchase_orders(ticket_id: Optional[int] = None) -> Dict[str, Any]:
    """List purchase orders and their status. Reads purchase_orders."""
    sql, params = "SELECT * FROM purchase_orders", ()
    if ticket_id is not None:
        sql, params = sql + " WHERE ticket_id = ?", (ticket_id,)
    rows = _rows(sql + " ORDER BY id", params)
    return {"count": len(rows), "purchase_orders": rows}


# ======================================================================================
# WRITE TOOLS -- the work the agents produce (no money moves here)
# ======================================================================================


@mcp.tool()
def save_draft_message(
    ticket_id: int,
    audience: str,
    subject: str,
    body: str,
    drafted_by: str,
) -> Dict[str, Any]:
    """Save a message draft to the board for a human to review and send.

    Writes drafts. Nothing is emailed and no vendor is contacted -- the draft stays on the
    board. audience is who it is addressed to, e.g. 'customer' or 'landlord'.

    Only for a ticket that has no draft yet. If one already exists, use revise_draft so the
    board holds one current message rather than a pile of stale ones.
    """
    ticket = _one("SELECT id FROM tickets WHERE id = ?", (ticket_id,))
    if ticket is None:
        return {"ok": False, "error": f"No ticket {ticket_id}; cannot attach a draft to it."}

    today = _today()
    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        cur = conn.execute(
            "INSERT INTO drafts (ticket_id, audience, subject, body, drafted_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, audience, subject, body, drafted_by, today),
        )
        draft_id = cur.lastrowid
    return {
        "ok": True,
        "draft_id": draft_id,
        "ticket_id": ticket_id,
        "audience": audience,
        "status": "saved_to_board_not_sent",
    }


@mcp.tool()
def revise_draft(draft_id: int, subject: str, body: str, revised_by: str) -> Dict[str, Any]:
    """Rewrite a draft that is already on the board, in place.

    Writes drafts. Use this instead of save_draft_message whenever a draft for this ticket
    already exists -- facts change between runs (an approval lands, a purchase order ships,
    a restock is cancelled), and a second near-identical draft leaves a human choosing
    between two messages where one is quietly out of date. Call list_drafts first to see
    whether you are writing a new message or correcting an old one.
    """
    row = _one("SELECT id, ticket_id, revision FROM drafts WHERE id = ?", (draft_id,))
    if row is None:
        return {"ok": False, "error": f"No draft {draft_id}."}

    today = _today()
    revision = (row["revision"] or 1) + 1
    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        conn.execute(
            "UPDATE drafts SET subject = ?, body = ?, drafted_by = ?, created_at = ?, "
            "revision = ? WHERE id = ?",
            (subject, body, revised_by, today, revision, draft_id),
        )
    return {
        "ok": True,
        "draft_id": draft_id,
        "ticket_id": row["ticket_id"],
        "revision": revision,
        "status": "revised_in_place_not_sent",
    }


@mcp.tool()
def update_ticket_status(ticket_id: int, status: str, resolution_note: str) -> Dict[str, Any]:
    """Set a ticket's status and append the reason to its notes.

    Writes tickets. Use 'resolved' when the work is finished, 'blocked' when it cannot move
    without something else happening first, 'awaiting_approval' when a human has to decide.
    """
    allowed = {"open", "in_progress", "awaiting_approval", "blocked", "resolved", "cancelled"}
    if status not in allowed:
        return {"ok": False, "error": f"status must be one of {sorted(allowed)}; got '{status}'."}

    ticket = _one("SELECT id, notes FROM tickets WHERE id = ?", (ticket_id,))
    if ticket is None:
        return {"ok": False, "error": f"No ticket {ticket_id}."}

    today = _today()
    note_line = f"[{today}] {status}: {resolution_note}"
    new_notes = f"{ticket['notes']}\n{note_line}" if ticket["notes"] else note_line
    with _connect(write=True) as conn:
        conn.execute(
            "UPDATE tickets SET status = ?, notes = ? WHERE id = ?",
            (status, new_notes, ticket_id),
        )
    return {"ok": True, "ticket_id": ticket_id, "status": status, "note_added": note_line}


@mcp.tool()
def create_purchase_order(
    ticket_id: int,
    vendor_id: int,
    sku: str,
    size: str,
    qty: int,
    created_by: str,
) -> Dict[str, Any]:
    """Draft a purchase order for restock. Refuses a vendor blocked by an unpaid invoice.

    Writes purchase_orders; reads vendors, invoices, pricing, desk. The unit cost comes from
    the pricing table, not from you, and the expected arrival is the shop's today plus the
    vendor's lead_days. The PO is created as draft_pending_approval: it commits no money until
    a human approves the spend.
    """
    if qty <= 0:
        return {"ok": False, "error": f"qty must be positive; got {qty}."}

    vendor = _one("SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?", (vendor_id,))
    if vendor is None:
        return {"ok": False, "error": f"No vendor {vendor_id}."}

    blockers = _rows(
        "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status != 'paid'",
        (vendor_id,),
    )
    if blockers:
        return {
            "ok": False,
            "error": "vendor_blocked_by_unpaid_invoice",
            "vendor": vendor["name"],
            "blocking_invoices": blockers,
            "message": (
                f"{vendor['name']} will not ship while invoice(s) "
                f"{[b['id'] for b in blockers]} are unpaid. Clear the invoice first, then "
                "re-create this purchase order."
            ),
        }

    price = _one("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,))
    if price is None:
        return {"ok": False, "error": f"No pricing row for sku={sku}; cannot cost this order."}
    if _one("SELECT 1 AS ok FROM inventory WHERE sku = ? AND size = ?", (sku, size)) is None:
        return {"ok": False, "error": f"The shop does not carry sku={sku} in size={size}."}

    today = _today()
    unit_cost = price["unit_cost"]
    total = round(unit_cost * qty, 2)
    eta = _add_days(today, vendor["lead_days"])

    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        cur = conn.execute(
            "INSERT INTO purchase_orders (ticket_id, vendor_id, sku, size, qty, unit_cost, "
            "total_cost, status, expected_arrival, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft_pending_approval', ?, ?, ?)",
            (ticket_id, vendor_id, sku, size, qty, unit_cost, total, eta, created_by, today),
        )
        po_id = cur.lastrowid
    return {
        "ok": True,
        "purchase_order_id": po_id,
        "vendor": vendor["name"],
        "sku": sku,
        "size": size,
        "qty": qty,
        "unit_cost": unit_cost,
        "total_cost": total,
        "expected_arrival": eta,
        "status": "draft_pending_approval",
        "next_step": (
            "Spending money needs a human: call request_payment_approval with "
            f"kind='purchase_order' and ref_id={po_id}."
        ),
    }


@mcp.tool()
def cancel_purchase_order(po_id: int, reason: str, cancelled_by: str) -> Dict[str, Any]:
    """Cancel a draft purchase order the shop will not be placing, e.g. one the cash cannot cover.

    Writes purchase_orders. Only a PO still at draft_pending_approval can be cancelled -- one that
    is already 'ordered' has been paid for and is not yours to undo. Cancelling moves no money; it
    stops a PO nobody can fund from sitting on the board as if it were waiting for a signature.
    """
    row = _one("SELECT id, status, total_cost FROM purchase_orders WHERE id = ?", (po_id,))
    if row is None:
        return {"ok": False, "error": f"No purchase order {po_id}."}
    if row["status"] != "draft_pending_approval":
        return {
            "ok": False,
            "error": f"Purchase order {po_id} is '{row['status']}' and cannot be cancelled.",
        }
    pending = _one(
        "SELECT id FROM approvals WHERE kind = 'purchase_order' AND ref_id = ? "
        "AND status IN ('pending', 'approved')",
        (po_id,),
    )
    if pending is not None:
        return {
            "ok": False,
            "error": f"Approval #{pending['id']} points at this purchase order; a human must "
            "deny it first.",
        }

    today = _today()
    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        conn.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (po_id,))
    return {
        "ok": True,
        "purchase_order_id": po_id,
        "status": "cancelled",
        "freed": row["total_cost"],
        "reason": reason,
        "cancelled_by": cancelled_by,
        "cancelled_at": today,
    }


@mcp.tool()
def request_payment_approval(
    kind: str,
    ref_id: int,
    amount: float,
    reason: str,
    requested_by: str,
    ticket_id: Optional[int] = None,
    account: str = "checking",
) -> Dict[str, Any]:
    """Queue a payment for a human to approve. This is the ONLY way money ever starts moving.

    Writes approvals; reads invoices, leases, purchase_orders, cash_accounts. kind is
    'invoice' (ref_id = invoice id), 'rent' (ref_id = lease id), or 'purchase_order'
    (ref_id = purchase order id). The amount you pass must equal what that record says is
    owed -- a mismatch is refused, so the figure can never come from an agent's memory.
    Creating a request moves no money: a human approves, and only then is it paid.
    """
    kind = kind.strip().lower()
    expected: Optional[float] = None
    target_desc = ""

    if kind == "invoice":
        row = _one(
            "SELECT i.id, i.amount, i.status, v.name AS vendor_name FROM invoices i "
            "JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
            (ref_id,),
        )
        if row is None:
            return {"ok": False, "error": f"No invoice {ref_id}."}
        if row["status"] == "paid":
            return {"ok": False, "error": f"Invoice {ref_id} is already paid."}
        expected, target_desc = row["amount"], f"invoice {ref_id} to {row['vendor_name']}"
    elif kind == "rent":
        row = _one("SELECT id, monthly_rent, space_name, next_due FROM leases WHERE id = ?", (ref_id,))
        if row is None:
            return {"ok": False, "error": f"No lease {ref_id}."}
        expected = row["monthly_rent"]
        target_desc = f"rent for {row['space_name']} due {row['next_due']}"
    elif kind == "purchase_order":
        row = _one("SELECT id, total_cost, status FROM purchase_orders WHERE id = ?", (ref_id,))
        if row is None:
            return {"ok": False, "error": f"No purchase order {ref_id}."}
        if row["status"] != "draft_pending_approval":
            return {"ok": False, "error": f"Purchase order {ref_id} is '{row['status']}'."}
        expected, target_desc = row["total_cost"], f"purchase order {ref_id}"
    else:
        return {"ok": False, "error": "kind must be 'invoice', 'rent', or 'purchase_order'."}

    if round(float(amount), 2) != round(float(expected), 2):
        return {
            "ok": False,
            "error": "amount_mismatch",
            "requested_amount": amount,
            "amount_on_record": expected,
            "message": (
                f"The record for {target_desc} says {expected}, not {amount}. "
                "Request the amount the table shows."
            ),
        }

    cash = _one("SELECT balance FROM cash_accounts WHERE name = ?", (account,))
    if cash is None:
        return {"ok": False, "error": f"No cash account '{account}'."}

    pending = _rows("SELECT amount FROM approvals WHERE status IN ('pending','approved')")
    committed = round(sum(p["amount"] for p in pending), 2)
    today = _today()

    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        cur = conn.execute(
            "INSERT INTO approvals (ticket_id, kind, ref_id, amount, account, reason, status, "
            "requested_by, requested_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (ticket_id, kind, ref_id, expected, account, reason, requested_by, today),
        )
        approval_id = cur.lastrowid

    return {
        "ok": True,
        "approval_id": approval_id,
        "status": "pending_human_approval",
        "kind": kind,
        "ref_id": ref_id,
        "amount": expected,
        "account": account,
        "for": target_desc,
        "cash_balance_now": cash["balance"],
        "already_committed_to_other_requests": committed,
        "cash_left_if_all_requests_are_paid": round(cash["balance"] - committed - expected, 2),
        "note": "No money has moved. A human has to approve this before it can be paid.",
    }


# ======================================================================================
# HUMAN-ONLY TOOLS -- the backend calls these for a person. Agents never get them.
# ======================================================================================


@mcp.tool()
def decide_approval(approval_id: int, decision: str, decided_by: str) -> Dict[str, Any]:
    """Record a HUMAN's approve/deny decision on a queued payment. Writes approvals.

    Not for agents: this is the human's half of the loop, called by the dashboard on behalf
    of the person named in decided_by.
    """
    decision = decision.strip().lower()
    if decision not in {"approved", "denied"}:
        return {"ok": False, "error": "decision must be 'approved' or 'denied'."}
    if not decided_by.strip():
        return {"ok": False, "error": "decided_by must name the person making the decision."}

    row = _one("SELECT id, status, amount, kind, ref_id FROM approvals WHERE id = ?", (approval_id,))
    if row is None:
        return {"ok": False, "error": f"No approval request {approval_id}."}
    if row["status"] != "pending":
        return {"ok": False, "error": f"Approval {approval_id} is already '{row['status']}'."}

    today = _today()
    with _connect(write=True) as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (decision, decided_by, today, approval_id),
        )
    return {
        "ok": True,
        "approval_id": approval_id,
        "status": decision,
        "decided_by": decided_by,
        "decided_at": today,
        "amount": row["amount"],
    }


@mcp.tool()
def pay_approved(approval_id: int) -> Dict[str, Any]:
    """Pay an approval a human already approved. Refuses anything else, and refuses to overdraw.

    Writes payments and cash_accounts, and settles what was paid: an invoice goes to 'paid',
    rent rolls next_due forward a month, a purchase order becomes 'ordered'. The payments row
    records approved_by from the human's decision. If the balance cannot cover the amount the
    whole thing is refused and nothing is written -- the account never goes negative.
    """
    approval = _one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if approval is None:
        return {"ok": False, "error": f"No approval request {approval_id}."}
    if approval["status"] == "paid":
        return {"ok": False, "error": f"Approval {approval_id} was already paid."}
    if approval["status"] != "approved":
        return {
            "ok": False,
            "error": "not_approved_by_a_human",
            "status": approval["status"],
            "message": (
                f"Approval {approval_id} is '{approval['status']}'. Payment requires a human "
                "approval on record."
            ),
        }

    amount, account = approval["amount"], approval["account"]
    cash = _one("SELECT name, balance FROM cash_accounts WHERE name = ?", (account,))
    if cash is None:
        return {"ok": False, "error": f"No cash account '{account}'."}
    if round(cash["balance"] - amount, 2) < 0:
        return {
            "ok": False,
            "error": "insufficient_funds",
            "balance": cash["balance"],
            "amount": amount,
            "shortfall": round(amount - cash["balance"], 2),
            "message": (
                f"Paying {amount} from '{account}' would leave "
                f"{round(cash['balance'] - amount, 2)}. Refused -- the account cannot go "
                "negative, and no revenue comes in to cover it."
            ),
        }

    today = _today()
    kind, ref_id = approval["kind"], approval["ref_id"]
    settled: Dict[str, Any] = {}

    with _connect(write=True) as conn:
        conn.executescript(WORKSPACE_SCHEMA)
        try:
            cur = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, ref_id, amount, account, today, approval["decided_by"]),
            )
            payment_id = cur.lastrowid

            new_balance = round(cash["balance"] - amount, 2)
            conn.execute(
                "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
                (new_balance, today, account),
            )

            if kind == "invoice":
                conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
                settled["invoice_status"] = "paid"
                vend = conn.execute(
                    "SELECT v.id, v.name FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
                    "WHERE i.id = ?",
                    (ref_id,),
                ).fetchone()
                if vend is not None:
                    still_open = conn.execute(
                        "SELECT COUNT(*) AS n FROM invoices WHERE vendor_id = ? AND status != 'paid'",
                        (vend["id"],),
                    ).fetchone()["n"]
                    settled["vendor"] = vend["name"]
                    settled["vendor_can_ship_now"] = still_open == 0
            elif kind == "rent":
                lease = conn.execute(
                    "SELECT next_due FROM leases WHERE id = ?", (ref_id,)
                ).fetchone()
                if lease is not None:
                    nxt = _add_one_month(lease["next_due"])
                    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, ref_id))
                    settled["lease_next_due"] = nxt
            elif kind == "purchase_order":
                conn.execute(
                    "UPDATE purchase_orders SET status = 'ordered' WHERE id = ?", (ref_id,)
                )
                settled["purchase_order_status"] = "ordered"

            conn.execute(
                "UPDATE approvals SET status = 'paid', payment_id = ? WHERE id = ?",
                (payment_id, approval_id),
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover - transaction safety net
            conn.rollback()
            return {"ok": False, "error": "payment_failed_rolled_back", "detail": str(exc)}

    return {
        "ok": True,
        "payment_id": payment_id,
        "approval_id": approval_id,
        "kind": kind,
        "ref_id": ref_id,
        "amount": amount,
        "account": account,
        "paid_at": today,
        "approved_by": approval["decided_by"],
        "balance_before": cash["balance"],
        "balance_after": new_balance,
        "settled": settled,
    }


if __name__ == "__main__":
    mcp.run()
