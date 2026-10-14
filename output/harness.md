# harness.md — Campus Customs Operations Harness

Running notes on the shop system my agent team operates. Started in Problem 2 (database study);
grows with each later problem.

- **Original DB (never written to):** `data/campus_customs.db`
- **Working copy (all tools read/write this):** `data/campus_customs_new.db`
- **Created with:** `cp data/campus_customs.db data/campus_customs_new.db` — verified identical
  (same MD5 `46effb90…`) and `pragma integrity_check` → `ok`.
- **Reset procedure:** re-run that same copy to throw away a run and start the tickets over.

---

## 1. The tables

### `desk` — 1 row
| Field | Type | Value today |
|---|---|---|
| `date_today` | TEXT | `2026-08-31` |
| `notes` | TEXT | *(empty)* |

**Why it matters:** this is the shop's clock — every "is it overdue?" and "will it arrive in
time?" decision is measured from this date, never from the real wall-clock date.

---

### `tickets` — 3 rows (all `open`)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 101, 102, 103 |
| `type` | TEXT | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT | person or org who raised it |
| `subject` | TEXT | one-line summary |
| `sku` | TEXT | nullable — set on product tickets |
| `size` | TEXT | nullable — pairs with `sku` |
| `qty` | INTEGER | nullable — how many units are wanted |
| `lease_id` | INTEGER FK → `leases.id` | nullable — set on space tickets |
| `invoice_id` | INTEGER FK → `invoices.id` | nullable — a bill attached to the ticket |
| `status` | TEXT | `open` now; agents move it to resolved/closed |
| `notes` | TEXT | free text from the requester |
| `created_at` | TEXT | ISO-8601 with `-04:00` offset |

**Why it matters:** this is the board — it's the agents' whole inbox, and its nullable FK columns
are what tell the boss which specialist to route a ticket to.

---

### `inventory` — 10 rows
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT | part of composite PK |
| `name` | TEXT | human-readable product name |
| `size` | TEXT | part of composite PK — `S/M/L/XL` or `OS` |
| `qty` | INTEGER | units on hand |
| `location` | TEXT | aisle in the shop |

**Why it matters:** stock is tracked **per size, not per SKU**, so the inventory agent has to
check the exact `(sku, size)` pair before it can call a shortfall.

---

### `pricing` — 4 rows
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT PK | one row per SKU — **no size dimension** |
| `unit_cost` | REAL | what the shop pays |
| `list_price` | REAL | what the customer pays |

**Why it matters:** the margin floor for discount requests — accounting needs both numbers to say
how deep a discount can go before a sale loses money.

---

### `vendors` — 3 rows
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 1, 2, 3 |
| `name` | TEXT | Bulldog Print Co, Elm City Gifts, QuickShip CT |
| `specialty` | TEXT | apparel reprint / mugs and small goods / local courier |
| `lead_days` | INTEGER | 5 / 3 / 1 |

**Why it matters:** picking a restock source is a two-part test — `specialty` has to match the
product, and `lead_days` from the desk date has to beat the customer's deadline.

---

### `leases` — 1 row
| Field | Type | Value |
|---|---|---|
| `id` | INTEGER PK | 1 |
| `space_name` | TEXT | Chapel Street shop |
| `landlord` | TEXT | Elm City Properties |
| `monthly_rent` | REAL | 2400.0 |
| `next_due` | TEXT | 2026-09-02 |
| `notes` | TEXT | *(empty)* |

**Why it matters:** the facilities agent's source of truth for rent — `next_due` vs. the desk date
says whether rent is upcoming or already late, and `monthly_rent` is the amount to queue for
approval.

---

### `cash_accounts` — 1 row
| Field | Type | Value |
|---|---|---|
| `name` | TEXT PK | checking |
| `balance` | REAL | 3400.0 |
| `date` | TEXT | 2026-08-31 |

**Why it matters:** the hard constraint on the whole run — one account, money only leaves it, and
the pay tool must refuse anything that would push the balance below zero.

---

### `payments` — 0 rows (agents write the first ones)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | rowid alias — SQLite assigns it |
| `kind` | TEXT | what was paid (e.g. invoice, rent) |
| `ref_id` | INTEGER | nullable — points at the invoice or lease paid |
| `amount` | REAL | amount debited |
| `account` | TEXT | which cash account it came from |
| `paid_at` | TEXT | timestamp of payment |
| `approved_by` | TEXT | **who approved it — the human-approval audit trail** |

**Why it matters:** this is the proof that a human approved before cash moved; `approved_by` must
never be filled in by an agent on its own authority.

---

### `invoices` — 1 row
| Field | Type | Value |
|---|---|---|
| `id` | INTEGER PK | 501 |
| `vendor_id` | INTEGER FK → `vendors.id` | 1 (Bulldog Print Co) |
| `amount` | REAL | 840.0 |
| `due_date` | TEXT | 2026-08-28 |
| `status` | TEXT | `open` |
| `description` | TEXT | Rush reprint CC-TEE-WHITE S |

**Why it matters:** an `open` invoice is a shipping blocker, not just a bill — the vendor it points
at refuses new product until it's cleared, so this table gates inventory work, not only accounting.

---

## 2. The three open tickets and how they link

### Ticket 101 — `customer_order`, Tauhid Zaman, "Bulldog tee"
`sku=CC-TEE-WHITE`, `size=S`, `qty=1`, `invoice_id=501`

The chain, and it's the whole assignment in one ticket:

```
ticket 101 ──sku+size──> inventory(CC-TEE-WHITE, S).qty = 0        ← shortfall of 1
           ──sku──────> pricing(CC-TEE-WHITE) cost 8.00 / list 28.00
           ──invoice_id> invoices(501) status=open, due 2026-08-28  ← 3 days overdue
                              └──vendor_id──> vendors(1) Bulldog Print Co
                                              specialty=apparel reprint, lead_days=5
```

The only vendor who can reprint this tee is the one sitting on the unpaid invoice, so the ticket
cannot be filled by inventory alone — it has to go through accounting, and then through a human
approval, before a restock is even possible. Earliest arrival is 2026-08-31 + 5 days = **2026-09-05,
and only if the $840 is paid first**.

### Ticket 102 — `rent_notice`, Elm City Properties, "Rent due"
`lease_id=1`, no sku/size/qty, no invoice

```
ticket 102 ──lease_id──> leases(1) Chapel Street shop
                         monthly_rent 2400.00, next_due 2026-09-02   ← 2 days out
```

Clean facilities ticket — not overdue yet, but it competes for the same cash as ticket 101.

### Ticket 103 — `price_override`, Yale AI Club, "Bulk hoodie discount"
`sku=CC-HOOD-NAVY`, `size=M`, `qty=20`, no invoice, no lease

```
ticket 103 ──sku+size──> inventory(CC-HOOD-NAVY, M).qty = 8          ← shortfall of 12
           ──sku──────> pricing(CC-HOOD-NAVY) cost 22.00 / list 58.00
```

Two questions in one ticket: how deep a discount still clears cost (inventory agent on the
shortfall, accounting on the margin), and whether the missing 12 units can be sourced at all —
which runs into the same blocked apparel vendor as ticket 101.

### What the linkage means for routing

| Column present | Routes to |
|---|---|
| `sku` + `size` | inventory (stock check), then pricing/accounting if money is involved |
| `lease_id` | facilities |
| `invoice_id` | accounting — and it's a blocker flag for inventory |
| none of the above | boss handles or sends to customer service |

---

## 3. Money and timing picture for the run

| Item | Amount | Date | Status vs. desk date 2026-08-31 |
|---|---|---|---|
| Starting cash (checking) | **3,400.00** | 2026-08-31 | — |
| Invoice 501 (Bulldog Print Co) | −840.00 | due 2026-08-28 | **overdue by 3 days**, blocks reprints |
| Rent, lease 1 | −2,400.00 | due 2026-09-02 | due in 2 days |
| **If both are paid** | **160.00 left** | | fits, with almost nothing to spare |

Consequences the agents have to respect:
1. **Both obligations fit, but barely** — $3,240 of $3,400. Any purchase order for the 12 missing
   hoodies (12 × $22 = $264) does **not** fit alongside both, so something has to be sequenced,
   partially filled, or deferred.
2. **No revenue** — nothing refills checking, so each approved payment permanently shrinks what's
   available for the next ticket.
3. **Order of operations matters** — paying invoice 501 is what unblocks Bulldog Print Co, so it
   has to clear before any reprint PO for ticket 101 or 103 is meaningful.

---

## 4. Schema gotchas to handle in tool code

- **SQLite doesn't enforce foreign keys by default** — connections need `PRAGMA foreign_keys=ON`
  or the FK declarations on `tickets` and `invoices` are decorative.
- **`inventory` PK is `(sku, size)`** — any stock update must filter on both, or it hits the wrong
  row or several rows.
- **`pricing` has no size column** — cost and price are per-SKU, so a size-M hoodie prices the same
  as a size-S one.
- **No CHECK constraints on `status`** anywhere — ticket and invoice status strings are whatever
  the tools write, so the tool layer has to standardize them.
- **No constraint stops `cash_accounts.balance` going negative** — the no-negative-balance rule
  lives entirely in the pay tool, not in the schema.
- **Dates are TEXT** — `desk.date_today`, `due_date`, and `next_due` are `YYYY-MM-DD` and compare
  correctly as strings; `tickets.created_at` is full ISO-8601 with an offset, so it does **not**
  compare directly against the others without truncating to the date part.
- **`payments` is empty** — the first row written is the first time cash moves in this run, and it
  must carry a real `approved_by`.

---

## 5. MCP tools (Problem 3)

Server lives in `mcp_server/server.py`, built with FastMCP, pointed at the working copy
`data/campus_customs_new.db`. All three tools are reads, so the connection opens read-only for
now. No tool invents a value: everything returned is a column read from a table or arithmetic
over columns read from tables, and a missing row comes back as `{"found": false}`.

| Tool | Table(s) read | Ticket unlocked |
|---|---|---|
| `check_stock(sku, size, qty_needed=None)` | `inventory` | **101** |
| `get_rent_due(lease_id)` | `leases`, plus `desk` for the shop's today | **102** |
| `get_sku_margin(sku, qty=None, proposed_unit_price=None)` | `pricing` | **103** |

### `check_stock(sku, size, qty_needed=None)`

- **Reads:** `inventory` — returns `qty` and `location` for one `(sku, size)` pair, and when
  `qty_needed` is supplied, `can_fill_now` and `shortfall`.
- **Unlocks ticket:** **101** — customer order, `CC-TEE-WHITE`, size `S`, qty 1.
- **Why it's the right tool for that ticket:** Ticket 101 names a SKU *and* a size, and inventory
  is keyed on both, so only a per-`(sku, size)` lookup reveals that this exact row is at **qty 0**
  while the same tee still has 5, 3, and 2 units in M, L, and XL — turning a ticket that looks
  fillable at the SKU level into a hard shortfall of 1 that forces the reprint path.

### `get_rent_due(lease_id)`

- **Reads:** `leases` for the lease row, and `desk.date_today` to date it — returns
  `monthly_rent`, `next_due`, `days_until_due`, and `is_overdue`.
- **Unlocks ticket:** **102** — rent notice from Elm City Properties, `lease_id = 1`.
- **Why it's the right tool for that ticket:** Ticket 102 carries no amount at all — just
  `lease_id = 1` and a note saying rent is due in two days — so this tool is what supplies the
  **$2,400** figure and the **2026-09-02** date from the lease row, and measuring them against
  `desk.date_today` (2026-08-31) proves the rent is upcoming rather than already late before
  facilities queues it for human approval.

### `get_sku_margin(sku, qty=None, proposed_unit_price=None)`

- **Reads:** `pricing` — returns `unit_cost`, `list_price`, `unit_margin`,
  `max_discount_pct_before_loss`, and `break_even_unit_price`; optional `qty` adds order totals and
  optional `proposed_unit_price` reports what a specific discount does to the margin.
- **Unlocks ticket:** **103** — Yale AI Club wants 20× `CC-HOOD-NAVY` in M at a bulk discount.
- **Why it's the right tool for that ticket:** Ticket 103 asks for a discount without naming a
  price, so accounting has nothing to answer with until this tool produces the **$22.00 cost against
  the $58.00 list** — a **$36.00** per-unit cushion, or at most **62.07% off** before a hoodie sells
  below what the shop paid — which converts "can we discount?" into a defensible floor instead of a
  guess.

### Not built yet (coming in later problems)

The vendor/invoice blocker check (`vendors` + `invoices`) that ticket 101 also needs, ticket status
updates, draft and purchase-order records, and the human-approved payment tool that writes
`payments` and debits `cash_accounts`.

---

## 6. Connecting the MCP server and smoke-testing it (Problem 4)

### Connection

`.mcp.json` at the project root registers the server for anyone who opens this repo:

```json
{
  "mcpServers": {
    "campus-customs": {
      "type": "stdio",
      "command": "./.venv/bin/python",
      "args": ["mcp_server/server.py"],
      "env": {}
    }
  }
}
```

Relative paths on purpose — this is a public repo, so a clone works from its own checkout without
anyone's home directory baked in. Setup is `python3 -m venv .venv && .venv/bin/pip install fastmcp`
(FastMCP 4.1.0 here, Python 3.13).

This machine's Claude Code reads its project MCP list from `/Users/jenniferpham/Desktop/AI
Foundation/.mcp.json` (one level above the repo), so `campus-customs` was added there too, with
absolute paths. That file is outside the repo and is not part of the submission.

### Smoke test

Evidence: **`output/mcp_smoke.json`**. Every tool was called over the real MCP stdio protocol, with
the server spawned from the exact command line in `.mcp.json`, and every value in every response
was checked back against `data/campus_customs_new.db`.

| Ticket | Tool | Arguments | Headline result | Matches DB |
|---|---|---|---|---|
| 101 | `check_stock` | `CC-TEE-WHITE`, `S`, needs 1 | `qty_on_hand: 0`, `can_fill_now: false`, `shortfall: 1` | ✅ |
| 102 | `get_rent_due` | `lease_id: 1` | `$2,400.00` due `2026-09-02`, `days_until_due: 2`, `is_overdue: false` | ✅ |
| 103 | `get_sku_margin` | `CC-HOOD-NAVY`, qty 20 | cost `$22.00` / list `$58.00`, max discount `62.07%`, margin at list `$720.00` | ✅ |

`tools_listed_by_server` came back as exactly the three tools, so nothing is untested, and
`all_outputs_match_db` is `true`.

### What the smoke test confirms about the tickets

- **101 cannot be picked from the shelf.** The size-S row really is at zero, so the ticket needs the
  reprint path, which runs straight into the unpaid invoice 501 blocking Bulldog Print Co.
- **102 is upcoming, not late.** `days_until_due: 2` against `desk.date_today` = 2026-08-31 — the
  rent is a scheduled obligation, so facilities can sequence it rather than treat it as an emergency.
- **103 has real room, but not unlimited.** $36.00 per hoodie of cushion and a 62.07% ceiling before
  selling below cost; at list the 20-unit order carries $720.00 of margin, which is the number
  accounting negotiates down from.

---

## 7. The agent team (Problem 5)

Built with PydanticAI. **Every agent runs `gpt-6-luna` through Portkey and nothing else** — the
model name is a constant in `backend/config.py`, and `PORTKEY_MODEL` from the environment is
deliberately ignored so a stale value in a shared `.env` cannot swap the model mid-run.

Each agent's system prompt is its own file in `backend/prompts/`, loaded at runtime.

| Agent | Prompt | Scope | Write tool it owns |
|---|---|---|---|
| **boss** | `prompts/boss.md` | Reads the ticket, routes it, weighs the trade-offs, makes the final call and closes the ticket out. | `update_ticket_status` |
| **inventory** | `prompts/inventory.md` | Stock by `(sku, size)`, shortfalls, partial fills, which vendor can restock and when. | `create_purchase_order` |
| **accounting** | `prompts/accounting.md` | Cash, invoices, overdue, margins and discount floors; the only agent that can queue a payment. | `request_payment_approval` |
| **facilities** | `prompts/facilities.md` | The Chapel Street lease, rent amounts and due dates, the landlord. | *(none — asks accounting for money)* |
| **customer_service** | `prompts/customer_service.md` | Writes what the shop says back to the requester, conditional on what is actually approved. | `save_draft_message` |

### Full connectivity, and the brakes on it

Every agent carries an `ask_teammate` tool naming all four others, so **any agent can delegate to
any other** — the boss is where a ticket starts, not a relay everything flows back through. The
validation run on ticket 102 went `boss → facilities → accounting`, with facilities asking
accounting to queue the rent because facilities holds no payment tool.

A fully connected team is also how a token budget disappears, so delegation is bounded in
`backend/agents.py` and every refusal is written to the audit trail:

| Brake | Limit | What it prevents |
|---|---|---|
| Depth | `MAX_DELEGATION_DEPTH = 2` | An endless chain of hand-offs; past depth 2 an agent must answer with what it has. |
| Cycles | An agent already in the chain cannot be re-asked | `A → B → A` ping-pong. |
| Fan-out | `MAX_DELEGATIONS_PER_AGENT = 3` | One agent polling the whole team to feel thorough. |
| Shared budget | One `RunUsage` + `UsageLimits` for the whole ticket (40 requests, 60 tool calls, 180k tokens) | A long chain running up a bill instead of running out of road. |
| Reasoning | `openai_reasoning_effort="none"` | Paying for reasoning tokens on five agents doing lookup-and-decide work. |

Each sub-agent returns a structured `SpecialistReport` (findings / recommendation / blockers) and
the boss returns a `TicketDecision`, so answers come back compact instead of as free-form essays.

### Audit trail

`output/audit_trail.json`, append-only across runs — a later run never erases an earlier one, and
a run that crashed stays in the record. Every agent-loop step is one entry: `run_started`,
`agent_started`, `model_response`, `tool_call`, `tool_result`, `delegation`,
`delegation_refused`, `agent_finished`, `agent_error`, `human_decision`, `payment_executed`,
`run_finished`. Each carries the run id, sequence number, real timestamp, ticket, agent, model,
delegation depth and chain, the tool name with its arguments and result, and token usage.
Oversized tool results are truncated with a marker rather than dropped. The validation run on
ticket 102 produced 41 entries end to end.

---

## 8. Every MCP tool and the table it uses

Server: `mcp_server/server.py`, over the working copy `data/campus_customs_new.db`.
Role column is the client-side scoping in `backend/shop_mcp.py`: **all five agents can read
everything**, writes are scoped to the role that owns the consequence, and the human-only tools
are in no agent's toolset at all.

### Reads — available to all five agents

| Tool | Table(s) it uses |
|---|---|
| `get_shop_today` | `desk` |
| `list_tickets` | `tickets` |
| `get_ticket` | `tickets`, plus `leases` / `invoices` for whatever it links to |
| `check_stock` | `inventory` |
| `list_stock_for_sku` | `inventory` |
| `get_sku_margin` | `pricing` |
| `get_rent_due` | `leases`, `desk` |
| `get_cash_balance` | `cash_accounts` |
| `list_open_invoices` | `invoices`, `vendors`, `desk` |
| `get_invoice` | `invoices`, `vendors`, `desk` |
| `find_restock_options` | `vendors`, `invoices`, `desk`, `pricing` |
| `list_pending_approvals` | `approvals` |
| `list_drafts` | `drafts` |
| `list_purchase_orders` | `purchase_orders` |

### Writes — scoped to one role each

| Tool | Table(s) it writes | Also reads | Agent |
|---|---|---|---|
| `update_ticket_status` | `tickets` | `desk` | boss |
| `create_purchase_order` | `purchase_orders` | `vendors`, `invoices`, `pricing`, `inventory`, `desk` | inventory |
| `request_payment_approval` | `approvals` | `invoices`, `leases`, `purchase_orders`, `cash_accounts`, `desk` | accounting |
| `save_draft_message` | `drafts` | `tickets`, `desk` | customer_service |
| `revise_draft` | `drafts` | `desk` | customer_service |
| `cancel_purchase_order` | `purchase_orders` | — | inventory |

### Human-only — no agent can reach these

| Tool | Table(s) it writes | Who calls it |
|---|---|---|
| `decide_approval` | `approvals` | The dashboard, on behalf of a named person |
| `pay_approved` | `payments`, `cash_accounts`, and settles `invoices` / `leases` / `purchase_orders` | The backend, after a human approved |

The three workspace tables (`drafts`, `approvals`, `purchase_orders`) are created by the server in
the working copy only. The original database keeps its nine original tables.

---

## 9. SAFETY

### Guardrails a real business would want when agents touch real customers and real money

**Money**
1. **No agent can move money, at all.** `decide_approval` and `pay_approved` are excluded from
   every agent toolset and reachable only through a separate human path. The strongest thing an
   agent can do is put a request in a queue. An agent that decides a payment is urgent still
   cannot make one.
2. **Approval is recorded against a person.** `payments.approved_by` is copied from the human's
   decision, not supplied by the requester, so the books say who authorised the spend.
3. **The amount comes from the record, not the requester.** A request must match the invoice,
   lease, or PO it points at to the penny, so a hallucinated figure is rejected at the door.
4. **No overdraft, enforced at the last moment.** The balance is re-checked inside the payment
   transaction, not when the request was queued, so two approvals that were each affordable alone
   cannot both go through. A refusal writes nothing.
5. **One irreversible step, done atomically.** The payment, the debit, and the settlement happen
   in a single transaction that rolls back as a unit.

**Customers and third parties**
6. **Nothing is sent.** Drafts land on the board for a person to send; there is no email or vendor
   call anywhere in the system, so a bad draft is an embarrassment in a review queue rather than
   in a customer's inbox.
7. **No promise without a tool behind it.** Prompts forbid stating a date, price, or quantity that
   did not come from a tool read, and anything depending on an unapproved payment has to be
   written as conditional.
8. **The shop's own clock.** Every deadline is measured from `desk.date_today`, so the team cannot
   be wrong about what is late because a server's timezone drifted.

**Operations**
9. **One data path.** Every shop fact goes through MCP. A rule added to a tool applies to all five
   agents at once, and there is no side channel to audit separately.
10. **Least privilege by role.** Inventory cannot queue payments; accounting cannot write to
    customers; facilities holds no write tools at all and must ask. A prompt-injected agent is
    confined to its own role's blast radius.
11. **Append-only audit trail.** Every model turn, tool call, argument, result, delegation and
    refusal is recorded with who, when, and at what depth — including failed runs. Nothing in the
    system can rewrite history.
12. **Destructive operations are not tools.** Resetting the database is a human-run script, so no
    agent can wipe the books.
13. **The working copy is the blast radius.** Agents only ever touch `campus_customs_new.db`; the
    original is read-only in practice and the recovery path is a file copy.

**What a real deployment would still need:** rate limits per ticket and per day, a maximum
auto-queued amount above which a second approver is required, PII redaction before customer text
goes to a model, prompt-injection screening of ticket text (a ticket body is untrusted input that
agents read), a dry-run mode, and alerting when an agent's refusal rate spikes.

### Limits that keep token use in check

| Limit | Where | Value |
|---|---|---|
| Delegation depth | `config.MAX_DELEGATION_DEPTH` | 2 |
| Teammates per agent per ticket | `config.MAX_DELEGATIONS_PER_AGENT` | 3 |
| Requests per ticket (shared) | `config.TICKET_USAGE_LIMITS` | 40 |
| Tool calls per ticket (shared) | `config.TICKET_USAGE_LIMITS` | 60 |
| Tokens per ticket (shared) | `config.TICKET_USAGE_LIMITS` | 180,000 |
| Reasoning tokens | `config.MODEL_SETTINGS` | off (`reasoning_effort="none"`) |
| Cycle prevention | `agents.ask_teammate` | an agent in the chain cannot be re-asked |
| Structured replies | `SpecialistReport` / `TicketDecision` | bounded fields instead of free-form essays |
| Audit entry size | `audit.MAX_RESULT_CHARS` | 4,000 chars, truncated with a marker |

The shared budget is the important one: the boss and every agent it pulls in draw from a single
allowance, so a deep chain exhausts the ticket's budget rather than multiplying it per agent. For
reference, the ticket 102 validation run cost **32,114 tokens across 11 requests and 12 tool
calls** with three agents involved.

---

## 10. Backend routes (Problem 7)

`backend/main.py`, FastAPI. Started from the `backend/` folder:

```bash
uvicorn main:app --reload --port 8000
```

The API holds **no SQL of its own** — every shop fact is read back through the MCP server, the
same way the agents see it. The one thing it adds is the human half of the loop.

### The six the dashboard needs

| Route | What it does |
|---|---|
| `GET /tickets` | The three tickets with `is_open` / `is_resolved` on each, plus the shop's today. |
| `POST /tickets/{id}/run` | Runs the agent team on one ticket; returns a `run_id` to poll, or the finished result with `{"wait": true}`. |
| `GET /events` | Recent agent events — what each agent said, every tool call with its arguments and result, every delegation; filter by `run_id`, `ticket_id`, or `after_seq` for incremental refresh. |
| `POST /approvals/{id}/approve` | A human approves a queued payment, and this is where cash actually changes — agents only ever prepare it. `POST /approvals/{id}/decide` is the same route with `"denied"` available. |
| `GET /cash` | The current `checking` balance from `cash_accounts`, plus what is already committed to pending approvals and what is genuinely uncommitted. |
| `POST /reset` | Restores the working copy from the untouched original for a fresh run; leaves the append-only audit trail intact. |

### Supporting routes the dashboard uses

| Route | What it does |
|---|---|
| `GET /tickets/{id}` | One ticket with its linked lease or invoice resolved. |
| `GET /runs/{run_id}` | Status and result of one agent run. |
| `GET /runs` | Every run this server process has started. |
| `GET /approvals` | The approval queue and where each request stands (pending / approved / denied / paid). |
| `GET /drafts` | Message drafts the agents left on the board — never sent. |
| `GET /purchase-orders` | Purchase orders inventory drafted, with status and expected arrival. |
| `GET /invoices` | Unpaid invoices and the vendors they are blocking. |
| `GET /health` | Liveness, the shop's today, and which model the team is on. |

CORS is open to `localhost:5173` and `localhost:3000` so the React dev server can call it.

### Verified end to end against a live server

| Step | Result |
|---|---|
| `POST /tickets/102/run` | `boss → facilities → accounting`, approval #1 queued for $2,400.00 |
| `GET /cash` before | balance $3,400.00, committed $2,400.00, uncommitted $1,000.00 |
| `POST /approvals/1/approve` | paid, `payment_id 1`, `approved_by "Jennifer Pham"`, lease `next_due` rolled to 2026-10-02 |
| `GET /cash` after | **$1,000.00** — the money actually moved, and only on the human's click |
| Approve the same one again | refused: `Approval 1 is already 'paid'` |
| `POST /reset` | back to 3 open tickets and $3,400.00, audit trail untouched |

### A defect this caught

The first run through the API ended `awaiting_approval` with **nothing actually queued** —
accounting read the cash, the lease and the invoices, then answered advisory-style ("this is
affordable and should be approved") without ever calling `request_payment_approval`. The ticket
looked handled and gave the human nothing to click.

Fixed in two places, both prompt-level, since the tool layer was behaving correctly:
- **accounting** — advice is not the job; if the analysis says pay, call the tool and report the
  approval id, and if not, say which of the four legitimate reasons applies.
- **boss** — before calling anything `awaiting_approval`, call `list_pending_approvals` and name
  the id; if nothing is queued, the work is not finished.

Worth noting as a class of failure: nothing was unsafe here — no money moved, no rule was broken.
The agents just produced a *plausible-looking non-result*, which is exactly what an audit trail and
a status that has to point at a real approval id are for.

---

## 11. The dashboard (Problem 8)

`frontend/`, React 19 + Vite + TypeScript. Started with `npm run dev`; talks to the backend at
`http://localhost:8000` via `VITE_API_BASE` in `frontend/.env`. Design rationale is in
`output/design.md`.

Three columns in the order work moves: **the board** (what came in) → **the floor** (the team
working it) → **your desk** (what needs a person). The checking balance lives in the top bar
because it is the constraint every decision collides with.

| Requirement | Where it lives |
|---|---|
| List all three tickets | Left column, `Board.tsx` — status tag, coloured edge, and the ticket's keys as chips |
| Pick one and start the team | Select a card → "Run the team" → `POST /tickets/{id}/run` |
| Show each agent saying/doing | Agent rail (live pulse on the active agent) + event feed polling `GET /events?after_seq=` every 1.2s |
| Mark resolved when done | Status tag + green left edge + a rotated `RESOLVED` rubber stamp |
| Summary of what each agent did | "Shift report" tab — the boss's verdict, then one card per agent with its tools as chips |
| Human approves a pay/purchase | Paper approval slips, `POST /approvals/{id}/decide` |
| Checking balance drops after a pay | Top-bar readout animates on decrease; committed-vs-free bar re-draws |

Three kinds of event read differently on purpose: **speech** is a tinted prose card, a **tool
call** is a flat monospace strip, and a **refusal** turns that strip red — a guardrail firing is
the most interesting thing in a run, not an error to hide. Delegation depth is rendered as
physical indentation, so `boss → inventory → accounting` staircases down the screen.

### Verified live in the browser

Ran ticket 101 from the UI end to end: boss consulted accounting and inventory, the ticket moved
to `awaiting_approval`, approval #1 for $840.00 appeared as a paper slip, and clicking
**Approve & pay** dropped checking from **$3,400.00 to $2,560.00** with the slip stamped `PAID`
and signed. Database reset afterwards.

### Ports, on this machine

Both **8000** and **5173** were already occupied by another project's servers, so verification ran
on 8001/5174. CORS allows 5173, 5174, 5175 and 3000 because Vite silently falls back when its
default port is busy.

---

## 12. The full run (Problem 9)

Database reset from `data/campus_customs.db` before the run. Starting checking balance:
**$3,400.00**. Shop date 2026-08-31. Model: `gpt-6-luna` for all five agents.

**All three tickets resolved.** Ending balance **$152.00**, which matches `cash_accounts`.

### Cash, itemised

| # | Ticket | What moved | Approval | Amount | Balance |
|---|---|---|---|---|---|
| — | — | starting balance after reset | — | — | **$3,400.00** |
| 1 | 101 | pay invoice 501 — unblocks Bulldog Print Co | #1, Jennifer Pham | −$840.00 | $2,560.00 |
| 2 | 101 | pay purchase order #1 — 1 tee @ $8.00, arrives 2026-09-05 | #2, Jennifer Pham | −$8.00 | $2,552.00 |
| 3 | 102 | pay rent on lease 1, due 2026-09-02 | #3, Jennifer Pham | −$2,400.00 | $152.00 |
| — | 103 | PO #2 ($264.00) **cancelled** — only $152.00 available | none queued | $0.00 | **$152.00** |

`SELECT SUM(amount) FROM payments` → **3248.0**; $3,400.00 − $3,248.00 = **$152.00** =
`SELECT balance FROM cash_accounts`. Every `payments` row carries `approved_by = 'Jennifer Pham'`.

### What the run exposed

Four defects, all found by running rather than by reading, and all fixed in prompts rather than in
the tool layer — the guardrails themselves never misfired:

1. **Advice instead of action (accounting).** Analysed the cash and said "this should be approved"
   without calling `request_payment_approval`. The ticket looked handled and gave the human nothing
   to click.
2. **Advice instead of action (inventory).** Reported "the vendor can ship now" without creating the
   purchase order.
3. **A PO with no approval behind it.** Inventory created PO #1 but nobody queued the payment for it,
   so it sat at `draft_pending_approval` waiting for a signature that could not be given. Fixed by
   having inventory hand off to accounting immediately after creating a PO — the full-connectivity
   path doing real work.
4. **Stale snapshots read as conflicts.** Paying rent rolls `leases.next_due` forward a month, so on
   re-read the boss saw "rent not due for 32 days" next to a ticket note saying payment was pending,
   and stalled on the apparent contradiction. It was right to be suspicious; the rule it needed was
   that tables are current and ticket text is a snapshot.

A fifth was a policy gap rather than a bug: the team kept marking ticket 101 `blocked` because the
tee had not physically arrived. Goods in transit on a PO that is ordered and paid is finished work,
not a blockage — that needed saying explicitly.

### Tickets take several runs, not one

A ticket that needs a human approval cannot finish in a single run: the team queues the request and
stops. Ticket 101 took 9 runs across two approval cycles, 102 took 7, and 103 took 2 — by which
point the prompts had learned from the other two. The number of runs is itself a signal: the more
approval gates a ticket has, the more times it comes back to the board.

### Artefacts

| File | What it holds |
|---|---|
| `output/resolved_tickets.json` | Per ticket: id, final status, outcome, each agent's contribution with the tools it used, and every human approval |
| `output/resolved_board.html` | Double-clickable page with a dashboard screenshot per resolved ticket |
| `output/desk_tickets.html` | Expected (written before) vs. Actual (written after) per ticket, plus the itemised Cash tab |
| `output/audit_trail.json` | Every agent-loop step from every run, appended across the whole assignment |
| `output/shots/` | The three screenshots |

---

## 13. What this harness covers

| Section | Subject |
|---|---|
| §1–3 | The 9 database tables, the three tickets and how they link, the money and timing picture |
| §4 | Schema gotchas the tool layer has to handle |
| §5, §8 | Every MCP tool and the table it uses — 15 reads/writes plus 2 human-only, 21 in total |
| §6 | Connecting the MCP server and the smoke test |
| §7 | The five agents, their prompts, full connectivity, and the limits on it |
| §9 | SAFETY — guardrails and token limits |
| §10 | The FastAPI routes |
| §11 | The React dashboard |
| §12 | The full run and the cash |

### Final tool count

**22 MCP tools:** 14 reads, 6 agent writes (`update_ticket_status`, `create_purchase_order`,
`cancel_purchase_order`, `request_payment_approval`, `save_draft_message`, `revise_draft`), and
2 human-only (`decide_approval`, `pay_approved`).

Two of those were added because the run demanded them, not because the design predicted them:

- **`cancel_purchase_order`** — ticket 103 produced a $264.00 purchase order the shop could not
  fund, and there was no honest way to take it off the board.
- **`revise_draft`** — ticket 101 produced *three* near-identical customer drafts, one per run,
  because `save_draft_message` only ever inserts. Two of them were factually stale by the end. The
  reflection on the Reflection tab named this as a defect; this is the fix. Verified by re-running
  ticket 101 after adding it: **no new draft was created** — customer service read the board, judged
  the existing draft current, and left it alone.
