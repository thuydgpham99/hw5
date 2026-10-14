"""Data types shared across the Campus Customs backend.

Three groups:
  1. Who the team is, and what one agent carries while it works a ticket (AgentName, TeamDeps).
  2. What an agent hands back (TicketDecision, SpecialistReport).
  3. What gets written to the audit trail and read by the dashboard (AuditEntry, views).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage

# ---------------------------------------------------------------------------------------
# The team
# ---------------------------------------------------------------------------------------

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]

AGENT_ROLES: Dict[str, str] = {
    "boss": "reads the ticket, decides who works it, makes the final call",
    "inventory": "stock by sku and size, shortfalls, which vendor can restock",
    "accounting": "cash, invoices, margins, and payments queued for human approval",
    "facilities": "the shop space: leases, rent, and the landlord",
    "customer_service": "drafts the message that goes back to the person who asked",
}


@dataclass
class TeamDeps:
    """Carried through every agent and every delegation while one ticket is worked.

    `depth` and `chain` are what stop a team with full connectivity from delegating in
    circles: each hop increments depth, and an agent already in the chain cannot be asked
    again on the same branch.
    """

    run_id: str
    ticket_id: int
    approver: str
    depth: int = 0
    chain: tuple = ()
    usage: RunUsage = field(default_factory=RunUsage)
    delegations_made: Dict[str, int] = field(default_factory=dict)
    # audit.RunRecorder; typed loosely so the data types stay free of backend imports.
    recorder: Optional[Any] = None


# ---------------------------------------------------------------------------------------
# What agents produce
# ---------------------------------------------------------------------------------------


class TicketDecision(BaseModel):
    """The boss's final call on one ticket."""

    ticket_id: int
    outcome: Literal["resolved", "awaiting_approval", "blocked", "cancelled"] = Field(
        description="Where the ticket ended up after the team worked it."
    )
    summary: str = Field(description="What the team found and decided, in plain language.")
    consulted: List[str] = Field(
        default_factory=list, description="Which teammates were asked for help."
    )
    actions_taken: List[str] = Field(
        default_factory=list,
        description="Concrete things written to the shop: POs drafted, approvals queued, "
        "drafts saved, status changes.",
    )
    waiting_on_human: List[str] = Field(
        default_factory=list,
        description="Anything a person has to approve or send before this can finish.",
    )
    next_step: str = Field(description="The single next thing that should happen.")


class SpecialistReport(BaseModel):
    """What a specialist hands back to whoever asked it."""

    agent: str
    findings: str = Field(description="The facts found, with the numbers from the tools.")
    recommendation: str = Field(description="What the asking agent should do about it.")
    blockers: List[str] = Field(
        default_factory=list, description="Anything stopping this from being done now."
    )


# ---------------------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------------------

AuditEvent = Literal[
    "run_started",
    "agent_started",
    "model_response",
    "tool_call",
    "tool_result",
    "delegation",
    "delegation_refused",
    "agent_finished",
    "agent_error",
    "human_decision",
    "payment_executed",
    "run_finished",
]


class AuditEntry(BaseModel):
    """One auditable step of one agent loop.

    Written append-only to output/audit_trail.json. Enough to reconstruct later who did
    what, with which tool, on whose instruction, and what it cost.
    """

    run_id: str
    seq: int
    recorded_at: str = Field(description="Real wall-clock time this step was recorded.")
    ticket_id: Optional[int] = None
    agent: str
    event: AuditEvent
    depth: int = 0
    chain: List[str] = Field(
        default_factory=list, description="Delegation path that led to this agent."
    )
    model: Optional[str] = Field(default=None, description="Model that produced the step.")
    summary: str = Field(default="", description="One line a human can skim.")
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    text: Optional[str] = Field(default=None, description="Model text, if the step had any.")
    usage: Optional[Dict[str, Any]] = Field(
        default=None, description="Token/request usage for the step."
    )
    error: Optional[str] = None


# ---------------------------------------------------------------------------------------
# Views the dashboard reads (filled from MCP reads, not from agent memory)
# ---------------------------------------------------------------------------------------


class TicketView(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    sku: Optional[str] = None
    size: Optional[str] = None
    qty: Optional[int] = None
    lease_id: Optional[int] = None
    invoice_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class ApprovalView(BaseModel):
    id: int
    ticket_id: Optional[int] = None
    kind: str
    ref_id: Optional[int] = None
    amount: float
    account: str
    reason: str
    status: str
    requested_by: str
    requested_at: str
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    payment_id: Optional[int] = None


class DraftView(BaseModel):
    id: int
    ticket_id: int
    audience: str
    subject: str
    body: str
    drafted_by: str
    created_at: str


class PurchaseOrderView(BaseModel):
    id: int
    ticket_id: Optional[int] = None
    vendor_id: int
    sku: str
    size: str
    qty: int
    unit_cost: float
    total_cost: float
    status: str
    expected_arrival: Optional[str] = None
    created_by: str
    created_at: str


class ApprovalDecision(BaseModel):
    """A human's decision coming in from the dashboard."""

    decision: Literal["approved", "denied"]
    decided_by: str = Field(min_length=1, description="The person deciding. Never an agent.")
