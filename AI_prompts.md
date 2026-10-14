# AI_prompts.md — Campus Customs Multi-Agent Operations

This is my log of the prompts I typed to my vibe coder (Claude Code, Opus 5) while building
HW 5. One section per problem. Each section has the problem number and title, the prompt(s)
I actually typed, and — where the first prompt didn't get me there — a follow-up prompt plus
a note on what was lacking.

Sections for problems I haven't started yet are marked **[pending]** and get filled in as I
work through them, so this file stays a real log rather than something written at the end. Their
numbers are my best guess until I'm given the real ones, and get corrected as each problem lands.

---

## Problem 1 — Vibe Coder Prompts

### Prompt 1 (initial, sets up the whole assignment)

> We are working on HW5. The scenario is Campus Customs — a multi-agent operations team that
> runs a campus merch shop. Open tickets land on a board: customer orders, rent, unpaid bills,
> discount requests, whatever the shop has to handle. I need to build 3 pieces that talk to
> each other: an MCP server, a FastAPI backend with a multi-agent team, and a React dashboard
> so a human can watch the agents work and approve requests.
>
> The agent team has full connectivity — any agent may delegate to any other agent for help.
> The agents are:
> 1. **Boss** — reads each ticket, decides who should work on it, makes the final call.
> 2. **Inventory** — checks stock by SKU and size, spots shortfalls, figures out which vendor
>    can restock.
> 3. **Accounting** — watches cash and invoices, checks margins, prepares payments and purchase
>    orders for human approval.
> 4. **Facilities** — handles the shop space side (leases, rent).
> 5. **Customer Service** — drafts messages to customers.
>
> Data lives in `data/campus_customs.db`. That's the original shop database — tables are desk,
> tickets, inventory, pricing, vendors, leases, cash_accounts, payments, invoices. My tools will
> update the database as tickets get resolved, so make a copy called
> `data/campus_customs_new.db` and point the MCP server and the backend at that working copy.
> Keep `campus_customs.db` untouched so I can reset whenever I want to restart resolving tickets.
>
> Rules of this shop:
> - `desk.date_today` is "today" for the shop — use that date to decide what is overdue, not the
>   real wall-clock date.
> - Vendor lead times come from the vendors table.
> - A vendor will not ship new product while they still have an open unpaid invoice.
> - Human approval is required for any payment. Points are deducted if this isn't enforced.
> - If a payment is made, update the relevant tables.
> - If there isn't enough cash, the pay tool must refuse — no negative balances.
> - Cash only goes out in this HW; we didn't model revenue, so no money comes in.
> - Before a full run to resolve tickets, reset the database to the original values.
> - Do NOT email customers or call real vendors — drafts stay on the board.
> - Use my `PORTKEY_API_KEY` for AI calls, and use **only gpt-6-luna through Portkey** for every
>   agent. Multi-agent chats burn tokens fast, and points are deducted if any other model shows
>   up in my code or in a run.
> - The final submission is a PUBLIC GitHub repo, so no secrets committed.
>
> Start with Problem 1: create `AI_prompts.md` at the start of the assignment and keep it updated
> as we work. It's the log of what I typed to my vibe coder. Describe each problem in my own
> words, one section per problem. Each section needs: the problem number and title, at least one
> prompt I typed, and one follow-up prompt if I needed one (plus one sentence on what was lacking
> after the first).

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the first prompt described the assignment but didn't
say anything about the actual shop data, so the log would have been generic — I wanted the prompt
file (and everything after it) grounded in the real tickets, balances, and the blocking unpaid
invoice before writing a single line of code.

> Before you write `AI_prompts.md`, open the database and read it: dump the schema and the
> contents of desk, tickets, inventory, pricing, vendors, invoices, leases, and cash_accounts.
> Tell me what the shop's "today" is, what the open tickets actually are, and where the traps are
> — which SKUs are out of stock, which invoices are overdue, and whether there's enough cash to
> cover everything that's due. Then write the file with that context in mind, and set up
> placeholder sections for the remaining problems so this stays a running log instead of
> something I backfill at the end.

**Shop state this surfaced (as of `desk.date_today` = 2026-08-31):**

| Thing | Value | Why it matters |
|---|---|---|
| Ticket 101 | Customer order, `CC-TEE-WHITE` size S, qty 1 | Stock is **0** — needs a reprint |
| Ticket 102 | Rent notice, lease 1, $2,400 due 2026-09-02 | Due in 2 days |
| Ticket 103 | Bulk discount, 20× `CC-HOOD-NAVY` size M | Only **8** in stock; margin call needed |
| Invoice 501 | $840 to Bulldog Print Co, due 2026-08-28, **open** | **3 days overdue** — blocks the reprint |
| Cash | checking = $3,400 | $840 + $2,400 = $3,240, so it fits but it's tight |

---

## Problem 2 — Study the Database, Start the Harness

### Prompt 1

> Study the Campus Customs database. Open `data/campus_customs.db` and look through every table
> and its fields. Copy the original file to `data/campus_customs_new.db` — later problems update
> that working copy. Study the 3 open tickets so you see how they link to the other tables.
>
> Start `output/harness.md`. For each table, list the fields and one short line on why that table
> matters for the agents. You'll keep growing this harness file in later problems.

**Follow-up needed:** none — one prompt was enough. I'd already had the vibe coder dump the schema
and every table while writing Problem 1, so it had the contents in context and the harness came
back complete on the first pass.

**What came out of it:**
- `data/campus_customs_new.db` created, verified byte-identical to the original (same MD5) with
  `pragma integrity_check` → `ok`. The original stays untouched as the reset source.
- `output/harness.md` with all 9 tables documented, the ticket→table link map, the cash/timing
  picture, and a list of schema gotchas the tool layer has to handle (FKs are off by default in
  SQLite, `inventory` is keyed on `(sku, size)`, nothing in the schema stops a negative balance,
  `created_at` is full ISO-8601 while the due dates are plain `YYYY-MM-DD`).
- The finding that drives the rest of the build: paying invoice 501 ($840) **and** rent ($2,400)
  costs $3,240 of the $3,400 on hand, leaving $160 — not enough for the 12 missing hoodies on
  ticket 103 ($264), so the agents have to sequence and defer rather than approve everything.

---

## Problem 3 — Build the MCP Server

### Prompt 1

> Build the MCP server. Write it in `mcp_server/` using FastMCP. It talks to
> `data/campus_customs_new.db`. You do NOT need to connect to it or run it in this problem.
>
> Every agent in this HW uses the tools in this MCP server, and I'll add more tools to it later.
> For now write **3 tools** you know you'll need for the tickets that are actually in the database.
> Keep the names clear. Never invent any data — only use information that's in the database.
>
> In `output/harness.md`, list each of the 3 MCP tools. For every tool include: which table it
> reads, which ticket it helps unlock (101, 102, 103), and ONE sentence on why that tool is the
> right one for that ticket. Vague lines like "reads inventory" score low — tie the tool to the
> ticket. Also add a short `mcp_server/README.md` explaining what the MCP server is for, which
> database file it uses, and the three tools it has.

**Follow-up needed:** none — the Problem 2 harness had already pinned down which column each ticket
hangs off, so "3 tools for the tickets in the database" resolved to one tool per ticket without me
having to steer it a second time.

**What came out of it:**
- `mcp_server/server.py` — FastMCP server on the working copy only, with `check_stock` (ticket 101),
  `get_rent_due` (ticket 102), and `get_sku_margin` (ticket 103). Path resolves from the repo root
  with a `CAMPUS_CUSTOMS_DB` override; the connection is read-only since all three tools are reads.
- `mcp_server/README.md` — purpose, the database file, and the three tools.
- `output/harness.md` §5 — each tool tied to its ticket with the specific numbers it surfaces
  (qty 0 in size S, $2,400 due 2026-09-02, $22 cost vs. $58 list = 62.07% max discount).
- Verified `server.py` compiles and that the three SQL queries return real rows from
  `campus_customs_new.db`. `fastmcp` isn't installed in my environment yet — not needed this
  problem, but it's a `pip install fastmcp` before the backend connects to it.

---

## Problem 4 — Connect the MCP Server and Test Each Tool

### Prompt 1

> Add the MCP server to the vibe coder and test each tool. Add my MCP server to this project so
> the vibe coder can call the tools. Save the connection JSON in `.mcp.json` at the project root
> (or however the vibe coder saves local MCP server lists).
>
> With the vibe coder connected, test EACH of my three MCP tools. Save the evidence in
> `output/mcp_smoke.json`. For every tool include: 1. the prompt I asked the vibe coder, 2. the
> tool name, 3. the tool output — and the output must match the values in
> `data/campus_customs_new.db`.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the first prompt got the server registered, but the
tools still weren't callable in my open chat — Claude Code reads its MCP list once at startup, and
it reads it from the folder *above* this repo, so writing `.mcp.json` alone proved nothing.

> Figure out where this machine's Claude Code actually reads its MCP server list from, and register
> `campus-customs` there as well as in the repo's own `.mcp.json` — keep the repo copy on relative
> paths since it's going to be public. Then don't just claim the tools work: actually call all three
> over the real MCP stdio protocol, spawning the server with the same command line that's in
> `.mcp.json`, and check every value in every response back against the database with SQL. Put the
> prompt, tool name, arguments, output, and the matching DB rows into `output/mcp_smoke.json`.

**What came out of it:**
- Python venv at `.venv` with FastMCP 4.1.0; `.mcp.json` at the project root with relative paths so
  a public clone works without my home directory in it.
- `campus-customs` also added to `/Users/jenniferpham/Desktop/AI Foundation/.mcp.json` (outside the
  repo), since that's the file this session's Claude Code actually loads. Backed it up first.
- `output/mcp_smoke.json` — all three tools called, each with the prompt, tool name, arguments,
  full output, the SQL used to verify it, and the matching rows. `all_outputs_match_db: true`.
- **Redone properly later.** On the first pass the tools were not callable in my open chat — Claude
  Code reads its MCP list once at startup, and that session predated `.mcp.json` — so I drove the
  server over the real MCP stdio protocol from a client script. After finishing the assignment I
  restarted the app, `campus-customs` connected, and I re-ran all three as genuine in-chat tool
  calls (`mcp__campus-customs__check_stock`, `get_rent_due`, `get_sku_margin`) against a freshly
  reset database. `mcp_smoke.json` now records that provenance explicitly, and the working copy was
  restored to the finished-run state afterwards so the other deliverables still match.
- Confirmed against the DB: tee size S is at **0** (shortfall 1), rent is **$2,400 due 2026-09-02,
  2 days out, not overdue**, hoodies are **$22 cost / $58 list → 62.07% max discount**.

---

## Problem 5 — Build the Agent Team and Grow the MCP Tools

### Prompt 1

> Build the agent team and grow the MCP tools. Build the agentic team for Campus Customs using
> PydanticAI: boss, inventory, accounting, facilities, and customer service. Include the prompts,
> the models, and the agent loops, so they can delegate work to each other with full connectivity.
>
> Put the agent prompts in `backend/prompts/` — ONE FILE PER AGENT. Put data types in
> `backend/models.py`, and the agent files under `backend/`. Use my `PORTKEY_API_KEY` and ONLY
> gpt-6-luna for every agent. Write each prompt in your own words with the shop rules that agent
> needs — detailed prompts that cover all aspects of an agent's work and scope score higher than
> a short generic prompt.
>
> Add any tools the agents need to the MCP server so they can work the open tickets. Shop facts
> come from the MCP server over `data/campus_customs_new.db` — do not invent a second shop-tools
> layer that bypasses MCP. Wire the agents so they append to `output/audit_trail.json` as they
> run: for each agent-loop step, record enough to audit later. Append to that file — do not wipe
> it each run.
>
> In `output/harness.md`, list each agent and each MCP tool (including the ones you add here)
> along with which table the tool uses. Add a short SAFETY section: the guardrails a real business
> would want when agents touch real customers and real money, plus limits that keep token use in
> check. Update `mcp_server/README.md` so the tool list matches what's there now.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the team ran, but the first live run died on a
provider error and the rules were still living in the prompts, where a model can talk itself out
of them — I wanted the guardrails moved into the tool layer and proven by actually trying to break
them.

> Two things. First, fix the run: gpt-6-luna rejected the call because function tools and
> `reasoning_effort` can't be combined on chat completions — turn reasoning off in the model
> settings rather than switching models, since I'm pinned to gpt-6-luna.
>
> Second, stop trusting the prompts to enforce the money rules. Put them in the MCP tools where an
> agent can't argue with them: the pay tool must refuse anything a human hasn't approved and must
> refuse to overdraw, a payment request must match the amount on the actual invoice or lease
> rather than whatever the agent types, and the approve/pay tools must not be in any agent's
> toolset at all. Then prove each refusal actually fires by calling the tools directly and showing
> me the output.

**What came out of it:**
- `backend/` — `config.py` (model pinned, Portkey wiring, limits), `models.py` (team types,
  agent outputs, audit entry, dashboard views), `audit.py` (append-only trail), `shop_mcp.py`
  (role-scoped MCP toolsets + the human-only path), `agents.py` (the five agents and
  `ask_teammate`), `team.py` (run a ticket, plus the human approve/pay path), `reset_db.py`.
- `backend/prompts/` — one detailed prompt per agent: scope, the shop rules that agent needs,
  which tools to use when, who to delegate to for what, what to report, and an explicit "never"
  list.
- MCP server grown from 3 tools to **20**: 14 reads, 4 agent writes, 2 human-only.
- **Guardrails verified by trying to break them**, not asserted: a PO to a vendor with an unpaid
  invoice is refused; a payment request for $800 against an $840 invoice is refused as
  `amount_mismatch`; `pay_approved` on a pending request is refused as `not_approved_by_a_human`;
  and paying $840 from a $500 balance is refused as `insufficient_funds` with **no payment row
  written and the balance unchanged**.
- Live validation run on ticket 102 went `boss → facilities → accounting` (depth 2, full
  connectivity working), queued approval #1 for $2,400 rent, set the ticket to
  `awaiting_approval`, moved no money, and wrote 41 audit entries for **32,114 tokens**. The
  earlier failed run is still in the trail above it, which is the append-only behaviour working.
- Model discrepancy worth flagging: my `.env` has `PORTKEY_MODEL=gpt-5.6-luna`, but the
  assignment requires gpt-6-luna. `config.py` ignores the env var and pins the model in code, and
  prints a warning when it sees the stale value.

---

## Problem 6 — Plan the Three Tickets

### Prompt 1

> Plan the three tickets. Before wiring the backend further, write down what you expect the team
> to do on each open ticket. Build `output/desk_tickets.html` — a page I can double-click — with
> ONE TAB PER TICKET (101, 102, 103), plus empty Cash and Reflection tabs for later problems
> (blank or a short "coming later" note).
>
> On each ticket tab, fill in an **Expected** section only, and leave room for an **Actual**
> section I'll fill after running the agents. For each Expected section, in my own words: 1. who
> the boss should call first and why, 2. ALL the agent delegations I expect — not "boss calls
> everyone", 3. which MCP tools I expect that run to use. Plans that send every specialist on
> every ticket score low. I'll compare this plan against what actually happens.

**Follow-up needed:** none. The harness work in Problems 2–5 had already pinned down which column
each ticket hangs off and which vendor is blocked, so the predictions came out of the data rather
than out of guesswork.

**What came out of it:**
- `output/desk_tickets.html` — standalone, no dependencies, five tabs.
- Each ticket gets a different, named chain rather than "the boss calls everyone":
  - **101**: `boss → inventory`, then `inventory → accounting` (the specialist-to-specialist hop,
    because inventory holds no payment tool), then `boss → customer_service`. **Facilities should
    not appear** — no `lease_id`.
  - **102**: `boss → facilities`, then `facilities → accounting`. Two delegations only.
    **Inventory should not appear**, and probably not customer service either.
  - **103**: `boss → accounting` (the ask is a price), then `accounting → inventory` (you cannot
    price 20 units you cannot supply), then `boss → customer_service`. **Facilities should not
    appear.**
- The prediction I most want to test: after $840.00 and $2,400.00 are committed, **$160.00**
  remains and the 12 missing hoodies cost **$264.00** — so ticket 103's restock is unaffordable. A
  good run defers it explicitly; a weak run queues a third approval anyway.

---

## Problem 7 — Backend Routes

### Prompt 1

> Backend routes. My React dashboard (next problem) needs a backend it can call. In
> `backend/main.py`, use FastAPI and add routes that: 1. return the three tickets and whether each
> is open or resolved, 2. take a ticket id and run the agents on that ticket, 3. return recent
> agent events — what each agent said and which tools they used — so the board can refresh,
> 4. approve a payment or purchase after a human clicks approve (agents only prepare the pay; this
> route is what actually changes cash), 5. return the current checking balance from
> `cash_accounts`, 6. reset the database to the original values for a fresh run.
>
> From the `backend/` folder I start it with `uvicorn main:app --reload --port 8000`, so the
> frontend can call those routes at `http://localhost:8000`. In `output/harness.md`, list each
> route in one line — what URL, what it does.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the routes worked, but the first real run through them
came back `awaiting_approval` with nothing in the approval queue — so the API was fine and the
agents were quietly producing a non-result.

> Don't just check the routes return 200 — drive the whole loop and show me the state changing.
> Run a ticket, then look at whether an approval actually exists before you tell me it worked. If
> the boss says `awaiting_approval` and the queue is empty, that's a bug: find out which agent
> stopped short and fix it. Then prove the money path: cash before, approve, cash after, and try to
> pay the same approval twice.

**What came out of it:**
- `backend/main.py` with the six required routes plus eight supporting ones. The API holds **no SQL
  of its own** — everything is read back through the MCP server, the same way the agents see it.
- **The defect the follow-up caught:** accounting read the cash, lease and invoices, then answered
  advisory-style ("affordable, should be approved") without ever calling
  `request_payment_approval`. Nothing unsafe happened — it was a plausible-looking non-result.
  Fixed in the accounting prompt (advice is not the job — queue it and report the id) and the boss
  prompt (before saying `awaiting_approval`, call `list_pending_approvals` and name the id).
- **Money path verified live:** cash $3,400.00 → approval #1 queued for $2,400.00 → human approves
  → paid, `approved_by "Jennifer Pham"`, lease rolled to 2026-10-02 → cash **$1,000.00**. Approving
  the same request twice is refused. `POST /reset` puts it back to 3 open tickets and $3,400.00
  with the audit trail intact.
- Note for running it: port **8000 was already occupied** by another uvicorn on this machine
  (looks like an earlier assignment's backend), so I verified on 8001. Stop that process before
  using the documented port.

---

## Problem 8 — Agent Dashboard

### Prompt 1

> Build the frontend dashboard in `frontend/` with React + Vite + TypeScript, calling the routes
> from Problem 7. At minimum the board should: 1. list all three tickets, 2. let me pick one and
> start the agent team on it, 3. show each agent and what they're saying/doing while it runs,
> 4. mark a ticket resolved when the run finishes, 5. show a short summary of what each agent did
> on that ticket, 6. let a human approve a pay or purchase when asked, 7. show the checking
> balance — it should drop after an approved pay.
>
> Make it look good. Be creative with the layout and feel — this is a real desk people would want
> to sit at, so put thought into how it looks. Point the frontend at `http://localhost:8000`, and
> allow the Vite origin (usually `http://localhost:5173`) on the backend. I start it with
> `npm run dev`.
>
> Write `output/design.md` with what I chose for the dashboard look — layout, how agents read
> differently, how resolved tickets and cash show up — and why, including the creative choices
> that make it feel special and something humans would actually enjoy using.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the first build compiled and looked right, but
"looks right in a screenshot" is not the same as "works" — nothing had proved the polling, the
approval click, or the balance actually dropping.

> Don't stop at the build passing. Start the backend and the dev server, open the page, click a
> real ticket, run the team, and show me the feed rendering while it works. Then click Approve &
> pay on the slip and screenshot the balance before and after. If the ports are taken, tell me
> rather than quietly using different ones.

**What came out of it:**
- `frontend/` — three columns in the order work moves: **the board** → **the floor** → **your
  desk**, with the cash readout pinned in the top bar because it is the constraint every decision
  collides with.
- The design decision I like most: **approval slips are the only light-coloured objects on the
  screen** — cream paper with a perforated edge on a dark desk. Things a human must act on look
  physical; everything an agent produced is digital. Once decided, the slip loses its paper and
  takes a rotated `PAID` / `DENIED` stamp.
- Three event types read differently on purpose — speech as a tinted prose card, tool calls as
  flat monospace strips, and **refusals in red**, because a guardrail firing is the most
  interesting thing in a run. Delegation depth is physical indentation, so a chain staircases
  down the screen.
- Agents never consulted stay grey and say `idle`, which makes **routing visible as an absence** —
  facilities sitting grey through ticket 101 is how you see the boss routed it correctly.
- **Verified live in the browser**, not just built: ran ticket 101 from the UI, watched the feed,
  clicked Approve & pay, and saw checking drop **$3,400.00 → $2,560.00** with the slip stamped and
  signed. Database reset afterwards.
- Ports: **8000 and 5173 are both already taken on this machine** by another project, so I
  verified on 8001/5174 and widened CORS to cover Vite's fallback ports.

---

## Problem 9 — Resolve the Tickets

### Prompt 1

> Resolve the tickets. Reset `data/campus_customs_new.db` so you start clean, and note the starting
> checking balance. Then run all three tickets (101, 102, 103) until each is **resolved**.
>
> Open `output/desk_tickets.html` from Problem 6 and fill the **Actual** section on each ticket tab
> from this run: which agents worked, what they delegated, which tools they used. Keep the Expected
> section so I can compare.
>
> On the Cash tab, itemise the money: 1. starting balance after the reset, 2. for EACH ticket, how
> cash changed when it resolved and why — which pay/purchase, what dollar amount, 3. the ending
> balance, which must match `cash_accounts` in the working database. **Wrong cash math loses points
> even if every ticket shows resolved.**
>
> Also save `output/resolved_tickets.json` (per ticket: id, final status, short outcome, what each
> agent contributed, any human approvals) and `output/resolved_board.html` — a double-clickable page
> with a screenshot of my React dashboard for each resolved ticket. Append the real runs to
> `output/audit_trail.json`, and finish `output/harness.md` so it covers tables, MCP tools, the five
> agents, API routes, the dashboard and safety rules.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the first pass through didn't actually finish anything
— tickets kept coming back `blocked` or `awaiting_approval` with nothing queued, so "run until
resolved" turned out to be the hard part rather than a formality.

> When a ticket doesn't resolve, don't just re-run it and hope. Find out which agent stopped short,
> read what it actually did in the audit trail, and fix the cause. And be honest in the Actual
> sections about where my plan was wrong, not just where it was right.

**What came out of it:**
- **All three tickets resolved.** Start **$3,400.00** → end **$152.00**, verified against
  `cash_accounts`: `SUM(payments.amount)` = $3,248.00, and $3,400.00 − $3,248.00 = $152.00.
  Three payments, three human approvals, all signed "Jennifer Pham".
- **Ticket 103 confirmed the prediction I most wanted to test.** With $152.00 left, the 12-unit
  hoodie restock at $264.00 was unaffordable, and the team said so itself — named the **$112.00
  gap**, refused to queue an unfundable approval, cancelled the PO, and offered the 8 units it
  actually had.
- **Four real defects, all found by running rather than reading**, and all fixed in prompts because
  the tool guardrails never misfired: accounting advising instead of queueing; inventory reporting a
  vendor was free instead of creating the PO; a PO left with no approval behind it; and the boss
  reading a post-payment lease date as a contradiction instead of a receipt.
- **A policy gap, not a bug:** the team kept marking 101 `blocked` because the tee hadn't physically
  arrived. Goods in transit on a PO that is ordered and paid is finished work — that needed saying.
- **One new MCP tool** fell out of the run: `cancel_purchase_order`, because ticket 103 produced a
  PO the shop couldn't fund and there was no honest way to take it off the board.
- Where my plan was **wrong**: I predicted 3 delegations on 101 and there were 5; I missed that a PO
  needs its *own* approval, so 101 cost two approvals not one; I got my own depth arithmetic wrong
  on 103; and I expected a 10–25% discount where the team offered none at all — on the grounds that
  no human had approved one, which is arguably better than my plan.

---

## Problem 10 — Reflection

### Prompt 1

> Reflection. Open `output/desk_tickets.html` and fill the Reflection tab. Answer in my own vibe,
> and be detailed and thorough: 1. how would I evaluate the agents' performance on each ticket and
> why, 2. for each ticket, how did Actual compare to the Expected plan, 3. what would have been
> simpler as one agent with tools — and WHY, 4. three NEW problems Campus Customs might face that
> this team could solve with the tools I built, 5. three NEW problems it could NOT solve, and the
> tools and agents I would need.
>
> Tie every answer to this app and the three tickets I ran — use the ticket tabs and the Cash tab
> as evidence. Generic AI essays without Campus Customs details score low.

**Follow-up needed:** none, but only because I made it go and get the evidence first: per-ticket
token totals and run counts out of the audit trail, the refusal events, and the actual draft bodies
out of the database. Writing the reflection off memory would have produced exactly the generic essay
the prompt warns about.

**What came out of it:**
- Per-ticket grades with evidence rather than vibes: **101 = C+** (right answer, 9 runs,
  373,125 tokens, two prompt fixes, three duplicate drafts), **102 = D** (correct but 276,089 tokens
  to read one number off one row — more than ticket 103 cost), **103 = A−** (2 runs, named the
  $112.00 gap itself, cancelled the PO, offered no discount because no human had approved one).
- The uncomfortable honest answer to question 3: **one agent with the same 21 tools would have been
  simpler for all three tickets.** None of the safety came from the agents conferring — all of it came
  from the tools refusing. The five-agent split bought separation of duties, which is real, but I paid
  ~827,000 tokens for a governance property a permission check also gives.
- Three solvable-today problems grounded in actual rows: the Crest Mug at qty 0 (same deadlock,
  but Elm City Gifts is unblocked so the PO would succeed first time), payables triage at $152.00,
  and a deadline question answerable from each vendor's `earliest_arrival_if_ordered_today`.
- Three unsolvable ones, each traced to a specific thing the run exposed: can't send or revise a
  message (ticket 101's three stale drafts), can't receive goods or take money in (PO #1 is
  permanently in transit; the clock is frozen at 2026-08-31; selling the 8 hoodies would add $0.00),
  and can't handle terms proposed by anyone outside the database (`amount_mismatch` is the guardrail
  that makes a rent increase unrepresentable).

---

## Problem 11 — Submit to GitHub

### Prompt 1

> Submit to GitHub. Push to a PUBLIC repo so graders can clone it, and put the URL in
> `output/github_url.txt` as well as Canvas. Do NOT push my real `.env`. DO include both database
> files under `data/` so graders can run it easily. Here's the expected file layout — tell me if we
> miss anything, we need exactly the same layout. The README should explain: copying the original
> DB to the working copy for a clean run, starting the MCP server, starting the FastAPI backend,
> starting the React board, and resetting the DB before a full three-ticket run.

### Prompt 2 (follow-up)

**What was lacking after the first prompt:** the repo was pushed and correct, but I wanted to know
how it would actually be marked — and then to act on the answer rather than just read it.

> If you had to grade this, what grade would you give? Then fix it.

**What came out of it:**
- Layout matched exactly. I removed `output/shots/` by base64-inlining the three screenshots into
  `resolved_board.html`, which both matches the required layout and makes the page self-contained
  when double-clicked.
- Verified against the **remote** tree, not the local one: 50 files, `.env` absent, both databases
  present, `gpt-6-luna` the only model named. Then cloned it fresh and confirmed a grader can reset
  and run it.
- Self-graded **A−**, with the honest weak points named: Problem 4's smoke test never went through a
  genuinely connected vibe coder, I edited the boss prompt mid-run to get ticket 101 to `resolved`,
  827k tokens is profligate, and I had diagnosed the duplicate-draft defect without fixing it.
- **Then fixed what was fixable:** added `revise_draft` (tool 22) and validated it by re-running
  ticket 101 — no duplicate draft was created; and replaced the hard-coded `./.venv/bin/python` in
  `.mcp.json` with `mcp_server/run.sh`, which finds whichever Python has `fastmcp`, so a clone works
  even if the virtualenv lives somewhere else.
