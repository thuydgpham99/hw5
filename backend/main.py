"""FastAPI backend for the Campus Customs dashboard.

Start it from the backend/ folder:

    uvicorn main:app --reload --port 8000

Everything the dashboard sees about the shop is read through the MCP server, the same way
the agents see it -- this API holds no SQL of its own. The one thing it adds is the human
half of the loop: the approve route is where cash actually moves, and no agent can reach it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import reset_db
from audit import new_run_id, read_trail
from config import DEFAULT_APPROVER, MODEL_NAME
from shop_mcp import read_shop
from team import decide_approval as human_decide_approval
from team import run_ticket

app = FastAPI(
    title="Campus Customs Operations",
    description="Backend for the agent dashboard. Shop data comes from the MCP server.",
    version="1.0.0",
)

# The React dev server runs on another port, so the browser needs this to call us.
app.add_middleware(
    CORSMiddleware,
    # 5173 is Vite's default; it falls back to 5174/5175 when that port is busy.
    allow_origins=[
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in (5173, 5174, 5175, 3000)
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-flight and finished agent runs, so the dashboard can poll one it started.
RUNS: Dict[str, Dict[str, Any]] = {}


class RunRequest(BaseModel):
    approver: str = Field(
        default=DEFAULT_APPROVER,
        description="Who will be asked to approve anything this run queues.",
    )
    wait: bool = Field(
        default=False,
        description="True blocks until the team finishes; False returns a run_id to poll.",
    )


class ApproveRequest(BaseModel):
    decision: str = Field(default="approved", description="'approved' or 'denied'.")
    decided_by: str = Field(
        default=DEFAULT_APPROVER, min_length=1,
        description="The person deciding. Recorded on the payment; never an agent.",
    )


# ---------------------------------------------------------------------------------------
# 1. The board
# ---------------------------------------------------------------------------------------


@app.get("/tickets", summary="The three tickets and whether each is open or resolved")
async def get_tickets() -> Dict[str, Any]:
    board = await read_shop("list_tickets")
    tickets = board.get("tickets", [])
    for t in tickets:
        # 'open' means still needs work; anything the team closed out is not open.
        t["is_open"] = t["status"] not in ("resolved", "cancelled")
        t["is_resolved"] = t["status"] == "resolved"
    return {
        "shop_today": board.get("shop_today"),
        "count": len(tickets),
        "open_count": sum(1 for t in tickets if t["is_open"]),
        "tickets": tickets,
    }


@app.get("/tickets/{ticket_id}", summary="One ticket with its linked lease or invoice")
async def get_one_ticket(ticket_id: int) -> Dict[str, Any]:
    ticket = await read_shop("get_ticket", ticket_id=ticket_id)
    if not ticket.get("found"):
        raise HTTPException(status_code=404, detail=f"No ticket {ticket_id}.")
    return ticket


# ---------------------------------------------------------------------------------------
# 2. Run the agent team on a ticket
# ---------------------------------------------------------------------------------------


async def _run_and_store(run_id: str, ticket_id: int, approver: str) -> None:
    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "running",
                    "result": None, "error": None}
    try:
        result = await run_ticket(ticket_id, approver=approver, run_id=run_id)
        RUNS[run_id].update(status="finished", result=result, error=result.get("error"))
    except Exception as exc:  # noqa: BLE001
        RUNS[run_id].update(status="failed", error=f"{type(exc).__name__}: {exc}")


@app.post("/tickets/{ticket_id}/run", summary="Run the agent team on one ticket")
async def run_ticket_route(
    ticket_id: int,
    body: Optional[RunRequest] = None,
) -> Dict[str, Any]:
    body = body or RunRequest()
    ticket = await read_shop("get_ticket", ticket_id=ticket_id)
    if not ticket.get("found"):
        raise HTTPException(status_code=404, detail=f"No ticket {ticket_id}.")

    run_id = new_run_id()
    if body.wait:
        await _run_and_store(run_id, ticket_id, body.approver)
        return RUNS[run_id]

    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "queued",
                    "result": None, "error": None}
    asyncio.create_task(_run_and_store(run_id, ticket_id, body.approver))
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "status": "started",
        "model": MODEL_NAME,
        "poll": f"/runs/{run_id}",
        "events": f"/events?run_id={run_id}",
    }


@app.get("/runs/{run_id}", summary="Status and result of one agent run")
async def get_run(run_id: str) -> Dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id} in this server process.")
    return run


@app.get("/runs", summary="Every agent run this server has started")
async def list_runs() -> Dict[str, Any]:
    return {"count": len(RUNS), "runs": list(RUNS.values())}


# ---------------------------------------------------------------------------------------
# 3. What the agents said and which tools they used
# ---------------------------------------------------------------------------------------


@app.get("/events", summary="Recent agent events, so the board can refresh")
async def get_events(
    limit: int = Query(default=100, ge=1, le=1000),
    run_id: Optional[str] = Query(default=None, description="Only one run's events."),
    ticket_id: Optional[int] = Query(default=None, description="Only one ticket's events."),
    after_seq: Optional[int] = Query(
        default=None, description="Only events after this seq, for incremental polling."
    ),
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = read_trail(run_id=run_id)
    if ticket_id is not None:
        entries = [e for e in entries if e.get("ticket_id") == ticket_id]
    if after_seq is not None:
        entries = [e for e in entries if (e.get("seq") or 0) > after_seq]
    recent = entries[-limit:]
    return {
        "count": len(recent),
        "total_in_trail": len(read_trail()),
        "latest_seq": recent[-1]["seq"] if recent else None,
        "events": recent,
    }


# ---------------------------------------------------------------------------------------
# 4. The human approves -- this is where cash actually moves
# ---------------------------------------------------------------------------------------


@app.get("/approvals", summary="Payments the agents queued, and where each one stands")
async def get_approvals() -> Dict[str, Any]:
    return await read_shop("list_pending_approvals")


@app.post("/approvals/{approval_id}/decide", summary="Approve or deny a queued payment")
async def decide(approval_id: int, body: Optional[ApproveRequest] = None) -> Dict[str, Any]:
    body = body or ApproveRequest()
    if body.decision not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'denied'.")

    # Approving pays it: decide_approval runs the human-only MCP tools, which refuse anything
    # not approved by a person and refuse to overdraw the account.
    outcome = await human_decide_approval(
        approval_id=approval_id,
        decision=body.decision,
        decided_by=body.decided_by,
        pay_if_approved=True,
    )
    if not outcome["decision"].get("ok"):
        raise HTTPException(status_code=400, detail=outcome["decision"].get("error"))

    payment = outcome.get("payment")
    return {
        "approval_id": approval_id,
        "decision": body.decision,
        "decided_by": body.decided_by,
        "paid": bool(payment and payment.get("ok")),
        "payment": payment,
        "cash_after": (payment or {}).get("balance_after"),
        "refused_reason": None if (payment is None or payment.get("ok")) else payment.get("message"),
    }


@app.post("/approvals/{approval_id}/approve", summary="Shorthand for approving and paying")
async def approve(approval_id: int, body: Optional[ApproveRequest] = None) -> Dict[str, Any]:
    body = body or ApproveRequest()
    body.decision = "approved"
    return await decide(approval_id, body)


# ---------------------------------------------------------------------------------------
# 5. Cash
# ---------------------------------------------------------------------------------------


@app.get("/cash", summary="The current checking balance from cash_accounts")
async def get_cash(account: str = Query(default="checking")) -> Dict[str, Any]:
    balance = await read_shop("get_cash_balance", account=account)
    if not balance.get("found"):
        raise HTTPException(status_code=404, detail=f"No cash account '{account}'.")
    approvals = await read_shop("list_pending_approvals")
    committed = sum(
        a["amount"] for a in approvals.get("approvals", [])
        if a["status"] in ("pending", "approved")
    )
    return {
        **balance,
        "committed_to_pending_approvals": round(committed, 2),
        "uncommitted": round(balance["balance"] - committed, 2),
        "note": "No revenue is modelled in this run: cash only goes out.",
    }


# ---------------------------------------------------------------------------------------
# 6. Reset
# ---------------------------------------------------------------------------------------


@app.post("/reset", summary="Reset the working database to the original values")
async def reset() -> Dict[str, Any]:
    reset_db.reset()
    RUNS.clear()
    board = await read_shop("list_tickets", status="open")
    cash = await read_shop("get_cash_balance", account="checking")
    return {
        "ok": True,
        "message": "Working copy restored from data/campus_customs.db.",
        "audit_trail": "left intact -- it is append-only across runs, including reset ones",
        "shop_today": board.get("shop_today"),
        "open_tickets": board.get("count"),
        "cash": cash.get("balance"),
    }


# ---------------------------------------------------------------------------------------
# Extras the dashboard uses to show the team's work
# ---------------------------------------------------------------------------------------


@app.get("/drafts", summary="Message drafts the agents left on the board (never sent)")
async def get_drafts(ticket_id: Optional[int] = None) -> Dict[str, Any]:
    return await read_shop("list_drafts", **({"ticket_id": ticket_id} if ticket_id else {}))


@app.get("/purchase-orders", summary="Purchase orders drafted by inventory")
async def get_purchase_orders(ticket_id: Optional[int] = None) -> Dict[str, Any]:
    return await read_shop(
        "list_purchase_orders", **({"ticket_id": ticket_id} if ticket_id else {})
    )


@app.get("/invoices", summary="Unpaid invoices, with the vendors they are blocking")
async def get_invoices() -> Dict[str, Any]:
    return await read_shop("list_open_invoices")


@app.get("/health", summary="Is the backend up, and which model is the team on")
async def health() -> Dict[str, Any]:
    today = await read_shop("get_shop_today")
    return {"ok": True, "model": MODEL_NAME, "shop_today": today.get("date_today")}
