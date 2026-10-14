# Campus Customs — Multi-Agent Operations

A five-agent team that runs the back office of a small Yale campus merch shop. Tickets land on
a board — customer orders, rent notices, unpaid bills, discount requests — and the team works
them: checking stock, chasing vendors, costing discounts, and preparing payments that **a human
has to approve before any cash moves.**

Three pieces that talk to each other:

| Piece | What it is |
|---|---|
| `mcp_server/` | A **FastMCP** server over the shop's SQLite database. 21 tools. The only way anything reads or writes the shop. |
| `backend/` | A **FastAPI** app plus a **PydanticAI** team of five agents — boss, inventory, accounting, facilities, customer service — all on `gpt-6-luna` through Portkey, with full connectivity between them. |
| `frontend/` | A **React + Vite + TypeScript** dashboard where you watch the agents work and sign off on payments. |

The shop's rules live in the MCP tools, not in the prompts, because a model can be talked into
anything and a tool that refuses cannot:

- `desk.date_today` is "today" — overdue and ETA maths never touch the wall clock.
- A vendor with an open unpaid invoice will not ship; `create_purchase_order` refuses them.
- `pay_approved` refuses anything a human has not approved, and refuses to overdraw the account.
- A payment request must match the invoice, lease, or purchase order it points at, to the penny.
- Nothing is ever sent. Drafts stay on the board for a person to send.
- `decide_approval` and `pay_approved` are in **no agent's toolset** — only the human path reaches
  them.

---

## Setup

### 1. Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Your Portkey key

```bash
cp .env.example .env
```

Then put your own key in `.env` as `PORTKEY_API_KEY=...`. That file is gitignored and is **not**
in this repo.

The model is pinned to `gpt-6-luna` in `backend/config.py`; `PORTKEY_MODEL` from the environment
is deliberately ignored so a stale value cannot swap the model mid-run.

### 3. The frontend

```bash
cd frontend && npm install
```

---

## The database

Two files ship with this repo so it runs out of the box:

| File | Role |
|---|---|
| `data/campus_customs.db` | **The original.** Never written to. This is the reset source. |
| `data/campus_customs_new.db` | **The working copy.** Everything — the MCP server, the backend, the agents — points here. |

The working copy in this repo holds the finished state of the full run (all three tickets
resolved, checking at $152.00). **Copy the original over it whenever you want a clean run:**

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

or, equivalently, with the reset summary printed for you:

```bash
.venv/bin/python backend/reset_db.py
```

The MCP server adds three tables to the working copy on first start — `drafts`, `approvals`,
`purchase_orders` — for work the original schema has nowhere to put. Resetting clears them.

---

## Running it

### 1. The MCP server

It does **not** need to be started by hand: the backend launches it over stdio, and `.mcp.json`
at the project root registers it for any MCP client (Claude Code picks it up automatically). To
run it directly:

```bash
.venv/bin/python mcp_server/server.py
```

### 2. The FastAPI backend

From the `backend/` folder:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Interactive API docs at <http://localhost:8000/docs>. Quick check:

```bash
curl localhost:8000/health
```

> If port 8000 is already in use, find the process with
> `lsof -nP -iTCP:8000 -sTCP:LISTEN` and stop it, or run on another port and set
> `VITE_API_BASE` for the frontend to match.

### 3. The React board

From the `frontend/` folder:

```bash
cd frontend
npm run dev
```

Opens on <http://localhost:5173> and talks to the backend at `http://localhost:8000`. (Override
with `VITE_API_BASE` in `frontend/.env` if your backend is elsewhere; the default is baked in, so
no `.env` is required.) The backend allows the Vite origin on 5173, plus 5174/5175 because Vite
silently falls back when its default port is busy.

---

## Doing a full three-ticket run

**Reset the database first** so you start from the three open tickets and $3,400.00 in checking:

```bash
.venv/bin/python backend/reset_db.py
```

Then, with the backend and the board both running:

1. **Pick ticket 101** on the left and press **Run the team**. Watch the feed: the boss reads the
   ticket, pulls in inventory, and inventory discovers that the only apparel-reprint vendor is
   frozen by an unpaid invoice.
2. **Approve the slip** that appears on the right ($840.00, invoice 501). Checking drops to
   $2,560.00 and the vendor unblocks.
3. **Run 101 again.** Inventory places the purchase order for the missing tee and accounting
   queues its approval ($8.00). Approve it, then run 101 once more to close it out.
4. **Ticket 102** — rent. One run queues $2,400.00; approve it; run again to resolve.
5. **Ticket 103** — the bulk discount. By now there is $152.00 left and the 12 missing hoodies cost
   $264.00, so watch the team work out the $112.00 gap and decline to spend money it does not have.

A ticket that needs an approval **cannot finish in one run** — the team queues the request and
stops, and you pick it up again after signing. That is the human-in-the-loop working, not a bug.

Prefer the command line? `.venv/bin/python backend/team.py 101` runs one ticket, and
`backend/team.py --all` runs every open one.

---

## Layout

```
hw5/
├── AI_prompts.md              every prompt typed while building this, one section per problem
├── requirements.txt
├── .env.example               copy to .env and add your Portkey key
├── .gitignore
├── .mcp.json                  MCP server registration
├── README.md
├── data/
│   ├── campus_customs.db      the original — never written to
│   └── campus_customs_new.db  the working copy — everything points here
├── mcp_server/
│   ├── server.py              21 tools; the shop's rules are enforced here
│   └── README.md
├── frontend/                  React + Vite + TypeScript dashboard
├── backend/
│   ├── main.py                FastAPI routes
│   ├── models.py              shared data types
│   ├── config.py              model pinned to gpt-6-luna, Portkey wiring, token limits
│   ├── agents.py              the five agents and the delegation tool
│   ├── team.py                runs a ticket; the human approve/pay path
│   ├── audit.py               append-only audit trail
│   ├── shop_mcp.py            role-scoped toolsets; the wall around the money
│   ├── reset_db.py            restore the working copy from the original
│   └── prompts/
│       ├── boss.md
│       ├── inventory.md
│       ├── accounting.md
│       ├── facilities.md
│       └── customer_service.md
└── output/
    ├── harness.md             the full build log: tables, tools, agents, routes, dashboard, safety
    ├── mcp_smoke.json         every MCP tool called and checked against the database
    ├── desk_tickets.html      plan vs. reality per ticket, the cash breakdown, the reflection
    ├── design.md              why the dashboard looks the way it does
    ├── resolved_tickets.json  final status, outcome, agent contributions, human approvals
    ├── resolved_board.html    a dashboard screenshot per resolved ticket
    ├── audit_trail.json       every agent-loop step from every run
    └── github_url.txt
```

Start with **`output/desk_tickets.html`** — it has a tab per ticket with what I predicted the
agents would do, what they actually did, the itemised cash, and an honest reflection on where the
plan was wrong.

---

## The run this repo records

Starting balance **$3,400.00** → ending balance **$152.00**, which matches `cash_accounts`.

| Ticket | What happened | Approval | Cash |
|---|---|---|---|
| 101 — Bulldog tee | Size S was at zero, and the only vendor who could reprint it was blocked by an unpaid invoice. Paid the invoice, ordered the tee (arrives 2026-09-05). | #1 $840.00, #2 $8.00 | −$848.00 |
| 102 — Rent due | $2,400.00 read off lease 1, queued by accounting at facilities' request, paid two days before it was due. | #3 $2,400.00 | −$2,400.00 |
| 103 — Bulk hoodies | 8 of 20 in stock. Restocking the other 12 costs $264.00 against $152.00 available, so the team cancelled the purchase order and offered what the shop actually had. | none — nothing affordable to queue | $0.00 |

Three payments, three human signatures. Every `payments` row carries `approved_by = "Jennifer
Pham"`, copied from the approval a person decided — no agent can write that column.

---

## Notes for graders

- **Every agent uses `gpt-6-luna` and nothing else.** The model name is a constant in
  `backend/config.py`, and it is the only model named anywhere in the code.
- **No secrets are committed.** `.env` is gitignored; `.env.example` shows what it needs.
- **The audit trail is append-only.** `output/audit_trail.json` holds every run from the whole
  assignment, including the ones that failed — a reset clears the database but never the trail.
- **Nothing was emailed and no vendor was contacted.** All six drafts are in the `drafts` table and
  on the board, unsent.
