"""Running the Campus Customs team over a ticket.

One ticket = one run = one MCP server subprocess = one shared token budget. The boss picks
the ticket up and pulls in whoever it needs; everything any agent does lands in
output/audit_trail.json as it happens.

Also holds the human half of the loop: when a person approves a queued payment, the
decision and the payment are executed here, through the human-only MCP tools, and recorded
in the same trail as the agents' work.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List, Optional

from pydantic_ai.exceptions import UsageLimitExceeded

from agents import build_team
from audit import RunRecorder, new_run_id
from config import DEFAULT_APPROVER, MODEL_NAME, TICKET_USAGE_LIMITS
from models import TeamDeps
from shop_mcp import build_shop_toolset, call_as_human, read_shop

BOSS_BRIEF = """Ticket #{ticket_id} is on the board at Campus Customs. You are on duty.

Start by reading the ticket with get_ticket so you are working from what the database says
rather than from the requester's wording. Decide who on the team should work it, pull them
in with ask_teammate, and make the final call.

Finish by setting the ticket's status with update_ticket_status, then report your decision.
"""


def _usage_dict(usage: Any) -> Dict[str, Any]:
    return {
        "requests": getattr(usage, "requests", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "tool_calls": getattr(usage, "tool_calls", None),
    }


async def run_ticket(
    ticket_id: int,
    approver: str = DEFAULT_APPROVER,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Work one ticket with the full team. Returns the boss's decision and what it cost."""
    run_id = run_id or new_run_id()
    recorder = RunRecorder(run_id, ticket_id)

    shop = build_shop_toolset()
    team = build_team(shop)
    deps = TeamDeps(run_id=run_id, ticket_id=ticket_id, approver=approver, recorder=recorder)

    recorder.record(
        "run_started",
        "boss",
        summary=f"Ticket #{ticket_id} picked up by the team (model {MODEL_NAME})",
    )
    recorder.record("agent_started", "boss", summary=f"boss opens ticket #{ticket_id}")

    decision: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    try:
        async with shop:
            result = await team["boss"].run(
                BOSS_BRIEF.format(ticket_id=ticket_id),
                deps=deps,
                usage=deps.usage,
                usage_limits=TICKET_USAGE_LIMITS,
            )
        recorder.record_agent_messages("boss", result.all_messages())
        decision = result.output.model_dump()
        recorder.record(
            "agent_finished",
            "boss",
            summary=f"boss ruled '{result.output.outcome}' on ticket #{ticket_id}",
            text=result.output.summary,
        )
    except UsageLimitExceeded as exc:
        error = f"usage limit reached: {exc}"
        recorder.record(
            "agent_error",
            "boss",
            summary=f"ticket #{ticket_id} stopped on its token budget",
            error=error,
        )
    except Exception as exc:  # noqa: BLE001 - the run must end with an audited outcome
        error = f"{type(exc).__name__}: {exc}"
        recorder.record(
            "agent_error", "boss", summary=f"ticket #{ticket_id} failed", error=error
        )

    usage = _usage_dict(deps.usage)
    recorder.record(
        "run_finished",
        "boss",
        summary=f"Ticket #{ticket_id} run complete",
        usage=usage,
        error=error,
    )
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "model": MODEL_NAME,
        "decision": decision,
        "error": error,
        "usage": usage,
        "delegations": dict(deps.delegations_made),
    }


async def run_open_tickets(approver: str = DEFAULT_APPROVER) -> List[Dict[str, Any]]:
    """Work every open ticket on the board, oldest first, one at a time.

    Sequential on purpose: the tickets compete for the same cash, so a later ticket has to
    see what an earlier one already committed.
    """
    board = await read_shop("list_tickets", status="open")
    ticket_ids = sorted(t["id"] for t in board.get("tickets", []))
    return [await run_ticket(tid, approver=approver) for tid in ticket_ids]


# ---------------------------------------------------------------------------------------
# The human half of the loop
# ---------------------------------------------------------------------------------------


async def decide_approval(
    approval_id: int,
    decision: str,
    decided_by: str,
    pay_if_approved: bool = True,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a person's approve/deny on a queued payment, and pay it if they approved.

    This is the only path money takes. It runs on the human-only MCP tools, which no agent
    can reach, and both halves land in the audit trail under the person's name.
    """
    run_id = run_id or new_run_id()
    recorder = RunRecorder(run_id, None)

    decided = await call_as_human(
        "decide_approval", approval_id=approval_id, decision=decision, decided_by=decided_by
    )
    recorder.record(
        "human_decision",
        "human",
        summary=f"{decided_by} {decision} approval #{approval_id}",
        tool_name="decide_approval",
        tool_args={"approval_id": approval_id, "decision": decision, "decided_by": decided_by},
        tool_result=decided,
        model=None,
    )
    if not decided.get("ok"):
        return {"decision": decided, "payment": None}

    payment = None
    if decision == "approved" and pay_if_approved:
        payment = await call_as_human("pay_approved", approval_id=approval_id)
        recorder.record(
            "payment_executed" if payment.get("ok") else "agent_error",
            "human",
            summary=(
                f"paid {payment.get('amount')} from {payment.get('account')}"
                if payment.get("ok")
                else f"payment refused: {payment.get('error')}"
            ),
            tool_name="pay_approved",
            tool_args={"approval_id": approval_id},
            tool_result=payment,
            error=None if payment.get("ok") else str(payment.get("error")),
            model=None,
        )
    return {"decision": decided, "payment": payment}


def _cli() -> None:
    """python backend/team.py [ticket_id | --all]"""
    args = sys.argv[1:]
    if not args:
        print(_cli.__doc__)
        raise SystemExit(2)
    if args[0] == "--all":
        results = asyncio.run(run_open_tickets())
    else:
        results = [asyncio.run(run_ticket(int(args[0])))]
    for r in results:
        print(f"\n=== ticket {r['ticket_id']} ({r['run_id']}) ===")
        if r["error"]:
            print("error:", r["error"])
        if r["decision"]:
            d = r["decision"]
            print("outcome:", d["outcome"])
            print("summary:", d["summary"])
            print("consulted:", ", ".join(d.get("consulted", [])) or "nobody")
            for action in d.get("actions_taken", []):
                print("  action:", action)
            for item in d.get("waiting_on_human", []):
                print("  waiting on human:", item)
            print("next step:", d["next_step"])
        print("usage:", r["usage"])


if __name__ == "__main__":
    _cli()
