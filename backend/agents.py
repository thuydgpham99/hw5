"""The Campus Customs agent team.

Five agents -- boss, inventory, accounting, facilities, customer service -- all on
gpt-6-luna through Portkey, all reading the shop through the MCP server.

**Full connectivity.** Every agent carries an `ask_teammate` tool listing all four of the
others, so any agent can delegate to any other. The boss is where a ticket starts, not a
bottleneck it has to flow back through: inventory can ask accounting about cash directly,
accounting can ask facilities about the lease, customer service can ask anyone what to
tell the customer.

Full connectivity is also how a team wastes a budget, so delegation is bounded:

  * depth -- a chain may go `MAX_DELEGATION_DEPTH` agents deep, then the agent has to
    answer with what it has instead of forwarding again;
  * cycles -- an agent already on the current branch cannot be asked again, so A->B->A
    cannot happen;
  * fan-out -- one agent may consult at most `MAX_DELEGATIONS_PER_AGENT` teammates per
    ticket;
  * budget -- every agent on a ticket shares one token/request allowance, so a long chain
    runs out of road rather than running up a bill.

Each refusal is written to the audit trail, so a chain that stopped early is visible
rather than silent.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Literal

from pydantic_ai import Agent, RunContext

from config import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_AGENT,
    PROMPTS_DIR,
    TICKET_USAGE_LIMITS,
    build_model,
)
from models import AGENT_ROLES, SpecialistReport, TeamDeps, TicketDecision
from shop_mcp import scoped_toolset

TeammateName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]

SPECIALISTS = ("inventory", "accounting", "facilities", "customer_service")
ALL_AGENTS = ("boss",) + SPECIALISTS


def load_prompt(name: str) -> str:
    """Read one agent's system prompt from backend/prompts/<name>.md."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt for agent '{name}' at {path}")
    return path.read_text(encoding="utf-8")


def _format_reply(agent_name: str, output: Any) -> str:
    """Flatten a teammate's structured answer into something the asking agent can read."""
    if isinstance(output, SpecialistReport):
        lines = [
            f"{agent_name.upper()} REPORTS",
            f"FINDINGS: {output.findings}",
            f"RECOMMENDATION: {output.recommendation}",
        ]
        if output.blockers:
            lines.append("BLOCKERS: " + "; ".join(output.blockers))
        return "\n".join(lines)
    if isinstance(output, TicketDecision):
        lines = [
            "BOSS RULES",
            f"OUTCOME: {output.outcome}",
            f"SUMMARY: {output.summary}",
            f"NEXT STEP: {output.next_step}",
        ]
        if output.waiting_on_human:
            lines.append("WAITING ON HUMAN: " + "; ".join(output.waiting_on_human))
        return "\n".join(lines)
    return str(output)


def _roster_for(asker: str) -> str:
    others = [a for a in ALL_AGENTS if a != asker]
    return "\n".join(f"  - {name}: {AGENT_ROLES[name]}" for name in others)


def _make_ask_teammate(asker: str):
    """Build the delegation tool for one agent, closed over who is doing the asking."""

    async def ask_teammate(
        ctx: RunContext[TeamDeps],
        teammate: TeammateName,
        question: str,
    ) -> str:
        """Ask another agent on the team for help and wait for their answer.

        Use this whenever a ticket needs something outside your own scope -- do not guess at
        another role's work. Ask one clear question with the facts you already have, so the
        teammate does not re-read what you just read.

        Args:
            teammate: Who to ask. The team is
%ROSTER%
            question: What you need from them, including the ticket number and the figures
                you already have.
        """
        deps: TeamDeps = ctx.deps
        recorder = deps.recorder
        chain = list(deps.chain)

        def refuse(reason: str) -> str:
            if recorder is not None:
                recorder.record(
                    "delegation_refused",
                    asker,
                    summary=f"{asker} -> {teammate} refused: {reason}",
                    depth=deps.depth,
                    chain=chain,
                    tool_name="ask_teammate",
                    tool_args={"teammate": teammate, "question": question},
                    error=reason,
                )
            return (
                f"Cannot delegate to {teammate}: {reason}. "
                "Answer with what you already have, and say plainly what is still unknown."
            )

        if teammate == asker:
            return refuse("an agent cannot delegate to itself")
        if teammate in chain:
            return refuse(f"{teammate} is already working this chain ({' -> '.join(chain)})")
        if deps.depth >= MAX_DELEGATION_DEPTH:
            return refuse(f"the delegation depth limit of {MAX_DELEGATION_DEPTH} is reached")

        used = deps.delegations_made.get(asker, 0)
        if used >= MAX_DELEGATIONS_PER_AGENT:
            return refuse(
                f"{asker} has already consulted {used} teammates on this ticket "
                f"(limit {MAX_DELEGATIONS_PER_AGENT})"
            )
        deps.delegations_made[asker] = used + 1

        if recorder is not None:
            recorder.record(
                "delegation",
                asker,
                summary=f"{asker} -> {teammate}: {question[:120]}",
                depth=deps.depth,
                chain=chain,
                tool_name="ask_teammate",
                tool_args={"teammate": teammate, "question": question},
            )

        sub_deps = replace(deps, depth=deps.depth + 1, chain=tuple(chain + [asker]))
        agent = AGENTS[teammate]

        if recorder is not None:
            recorder.record(
                "agent_started",
                teammate,
                summary=f"{teammate} picks up a question from {asker}",
                depth=sub_deps.depth,
                chain=list(sub_deps.chain),
            )

        try:
            result = await agent.run(
                f"Ticket #{deps.ticket_id}. {asker} asks: {question}",
                deps=sub_deps,
                usage=deps.usage,          # one shared budget for the whole ticket
                usage_limits=TICKET_USAGE_LIMITS,
            )
        except Exception as exc:  # a teammate failing must not kill the whole ticket
            if recorder is not None:
                recorder.record(
                    "agent_error",
                    teammate,
                    summary=f"{teammate} failed while answering {asker}",
                    depth=sub_deps.depth,
                    chain=list(sub_deps.chain),
                    error=f"{type(exc).__name__}: {exc}",
                )
            return (
                f"{teammate} could not answer ({type(exc).__name__}). Proceed with what you "
                "have and flag that their input is missing."
            )

        if recorder is not None:
            recorder.record_agent_messages(
                teammate,
                result.all_messages(),
                depth=sub_deps.depth,
                chain=list(sub_deps.chain),
            )
            recorder.record(
                "agent_finished",
                teammate,
                summary=f"{teammate} answered {asker}",
                depth=sub_deps.depth,
                chain=list(sub_deps.chain),
                text=_format_reply(teammate, result.output),
            )

        return _format_reply(teammate, result.output)

    # Bake the roster into the tool description so the model sees who it can reach.
    ask_teammate.__doc__ = (ask_teammate.__doc__ or "").replace("%ROSTER%", _roster_for(asker))
    return ask_teammate


def build_agent(name: str, shop_toolset: Any) -> Agent:
    """Build one agent: its prompt, the one model, its scoped MCP tools, and its teammates."""
    output_type = TicketDecision if name == "boss" else SpecialistReport
    return Agent(
        build_model(),
        name=name,
        instructions=load_prompt(name),
        deps_type=TeamDeps,
        output_type=output_type,
        toolsets=[scoped_toolset(shop_toolset, name)],
        tools=[_make_ask_teammate(name)],
        retries=2,
    )


AGENTS: Dict[str, Agent] = {}


def build_team(shop_toolset: Any) -> Dict[str, Agent]:
    """Build all five agents against one shared MCP connection and register them."""
    AGENTS.clear()
    for name in ALL_AGENTS:
        AGENTS[name] = build_agent(name, shop_toolset)
    return AGENTS


__all__ = [
    "AGENTS",
    "ALL_AGENTS",
    "SPECIALISTS",
    "build_team",
    "build_agent",
    "load_prompt",
]
