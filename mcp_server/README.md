# Campus Customs MCP Server

## What it is for

This is the single door between the Campus Customs agent team and the shop's data. Every
agent — boss, inventory, accounting, facilities, and customer service — reads and writes the
shop through these MCP tools, and there is no second shop-tools layer anywhere in the
project that bypasses it.

That matters because the shop's rules live in this layer rather than in the prompts. A model
can be talked into anything; a tool that refuses cannot. Enforced here:

- **`desk.date_today` is "today".** Overdue and ETA math uses it, never the wall clock.
- **A vendor with an open unpaid invoice will not ship.** `create_purchase_order` refuses
  them outright and names the invoice that is blocking it.
- **Money only moves through a human's approval.** `pay_approved` refuses anything that is
  not `status='approved'`, and the `payments.approved_by` column records the person.
- **The account can never go negative.** `pay_approved` refuses and writes nothing at all if
  the balance will not cover the amount — there is no revenue in this model to recover from
  an overdraft.
- **Amounts are never taken on an agent's word.** A payment request must match the invoice,
  lease, or purchase order it points at, to the penny.
- **Nothing is sent.** `save_draft_message` puts a draft on the board. No email, no vendor
  call.
- **Tools never invent data.** Every value is a column read or arithmetic over columns read;
  a missing row returns `{"found": false}`.

Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Which database file it uses

`data/campus_customs_new.db` — the **working copy**, resolved relative to the repo root. The
original `data/campus_customs.db` is never opened by this server; it stays untouched as the
reset source (`python backend/reset_db.py`).

Path can be overridden with `CAMPUS_CUSTOMS_DB` (used for tests). Read tools open the file
read-only; write tools take their own read-write connection.

The server adds three tables to the working copy on first start, for work the original
schema has nowhere to put: `drafts`, `approvals`, and `purchase_orders`. Resetting the run
re-copies the original and clears them.

## The tools

### Reads — the board and the shop's state

| Tool | Table(s) |
|---|---|
| `get_shop_today()` | `desk` |
| `list_tickets(status=None)` | `tickets` |
| `get_ticket(ticket_id)` | `tickets` + linked `leases` / `invoices` |
| `check_stock(sku, size, qty_needed=None)` | `inventory` |
| `list_stock_for_sku(sku)` | `inventory` |
| `get_sku_margin(sku, qty=None, proposed_unit_price=None)` | `pricing` |
| `get_rent_due(lease_id)` | `leases` + `desk` |
| `get_cash_balance(account="checking")` | `cash_accounts` |
| `list_open_invoices()` | `invoices` + `vendors` + `desk` |
| `get_invoice(invoice_id)` | `invoices` + `vendors` + `desk` |
| `find_restock_options(sku=None)` | `vendors` + `invoices` + `desk` (+ `pricing`) |
| `list_pending_approvals()` | `approvals` |
| `list_drafts(ticket_id=None)` | `drafts` |
| `list_purchase_orders(ticket_id=None)` | `purchase_orders` |

### Writes — the work the agents produce (no money moves)

| Tool | Table(s) | Refuses when |
|---|---|---|
| `save_draft_message(ticket_id, audience, subject, body, drafted_by)` | `drafts` | the ticket does not exist |
| `revise_draft(draft_id, subject, body, revised_by)` | `drafts` | the draft does not exist |
| `update_ticket_status(ticket_id, status, resolution_note)` | `tickets` | the status is not a known one |
| `create_purchase_order(ticket_id, vendor_id, sku, size, qty, created_by)` | `purchase_orders` (reads `vendors`, `invoices`, `pricing`, `desk`) | the vendor has an unpaid invoice, the SKU has no price, or the shop does not carry that size |
| `cancel_purchase_order(po_id, reason, cancelled_by)` | `purchase_orders` | the PO is already ordered, or an approval still points at it |
| `request_payment_approval(kind, ref_id, amount, reason, requested_by, ticket_id=None, account="checking")` | `approvals` (validates against `invoices` / `leases` / `purchase_orders`) | the amount does not match the record, or the record is already settled |

### Human-only — the backend calls these for a person

These are **never** handed to an agent. `backend/shop_mcp.py` scopes each agent's toolset and
excludes them; the human path goes through its own client in `call_as_human`.

| Tool | Table(s) | Refuses when |
|---|---|---|
| `decide_approval(approval_id, decision, decided_by)` | `approvals` | the request is already decided, or no person is named |
| `pay_approved(approval_id)` | `payments`, `cash_accounts`, and settles `invoices` / `leases` / `purchase_orders` | the approval is not `approved`, or the balance cannot cover it |

A successful `pay_approved` writes the payment, debits the account, and settles what was
paid: an invoice goes to `paid` (which unblocks that vendor), rent rolls `next_due` forward a
month, a purchase order becomes `ordered`.

## Running it

Registered in `.mcp.json` at the project root, so a vibe coder picks it up automatically.
To run it by hand:

```bash
./mcp_server/run.sh
```

That launcher finds whichever Python has `fastmcp` installed (the repo's `.venv` first, then
`venv`, then the system interpreter), so a clone works without the virtualenv being in an exact
place. `.mcp.json` points at it.

Dependencies: `pip install fastmcp` (developed against FastMCP 4.1.0, Python 3.13).

## Deliberately not a tool

**Resetting the database.** `python backend/reset_db.py` is a human-run script. No agent
should be able to erase the shop's books, so the reset is not reachable over MCP.
