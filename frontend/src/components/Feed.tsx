/**
 * The live floor: the agent rail, the event feed, and the shift report.
 *
 * The feed's whole job is to make three different kinds of thing read differently at a
 * glance -- an agent talking, an agent using a tool, and an agent handing work to someone
 * else -- without the reader having to parse labels.
 */
import { AGENT_ORDER, agentMeta, agentVars } from "../agents";
import type { AgentEvent, RunState } from "../types";

const clock = (iso: string) => {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
};

const shortArgs = (args: Record<string, unknown> | null): string => {
  if (!args) return "";
  const parts = Object.entries(args)
    .filter(([k]) => k !== "question")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  const joined = parts.join(" ");
  return joined.length > 120 ? joined.slice(0, 120) + "…" : joined;
};

/** Did this tool result refuse? Refusals are the guardrails working and must be visible. */
const isRefusal = (result: unknown): boolean => {
  const text = typeof result === "string" ? result : JSON.stringify(result ?? "");
  return (
    /"ok":\s*false/.test(text) ||
    /blocked_by_unpaid_invoice|insufficient_funds|amount_mismatch|not_approved_by_a_human/.test(
      text
    )
  );
};

const resultGist = (result: unknown): string => {
  if (result === null || result === undefined) return "";
  const text = typeof result === "string" ? result : JSON.stringify(result);
  return text.length > 160 ? text.slice(0, 160) + "…" : text;
};

/* ----------------------------- the agent rail ----------------------------- */

export function AgentRail({
  events,
  activeAgent,
}: {
  events: AgentEvent[];
  activeAgent: string | null;
}) {
  return (
    <div className="rail">
      {AGENT_ORDER.map((key) => {
        const meta = agentMeta(key);
        const mine = events.filter((e) => e.agent === key);
        const tools = mine.filter((e) => e.event === "tool_call" && e.tool_name !== "final_result");
        const used = mine.length > 0;
        const active = activeAgent === key;
        return (
          <div
            key={key}
            className={`agentcard ${active ? "active" : ""} ${used ? "used" : ""}`}
            style={agentVars(key)}
          >
            <div className="top">
              <div className="avatar" style={agentVars(key)}>
                {meta.initials}
              </div>
              <div className="name">{meta.label}</div>
              <div className={`dot ${active ? "live" : ""}`} />
            </div>
            <div className="role">{meta.role}</div>
            <div className="stat">
              {active
                ? "working…"
                : used
                ? `${tools.length} tool${tools.length === 1 ? "" : "s"}`
                : "idle"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------- the feed -------------------------------- */

function EventRow({ e }: { e: AgentEvent }) {
  const meta = agentMeta(e.agent);
  const style = agentVars(e.agent);
  const depthClass = e.depth >= 2 ? "d2" : e.depth === 1 ? "d1" : "d0";

  if (e.event === "run_started")
    return <div className="milestone">ticket #{e.ticket_id} picked up</div>;
  if (e.event === "run_finished") return <div className="milestone good">run complete</div>;
  if (e.event === "payment_executed")
    return <div className="milestone good">💵 {e.summary}</div>;
  if (e.event === "human_decision") return <div className="milestone">🖊 {e.summary}</div>;
  if (e.event === "agent_error")
    return (
      <div className="milestone bad">
        {e.agent}: {e.error ?? e.summary}
      </div>
    );

  // A hand-off gets its own row: who asked whom, and what they asked.
  if (e.event === "delegation" || e.event === "delegation_refused") {
    const to = String(e.tool_args?.teammate ?? "");
    const q = String(e.tool_args?.question ?? "");
    const refused = e.event === "delegation_refused";
    return (
      <div className={`ev ${depthClass}`} style={style}>
        <div className="body">
          <div className={`handoff ${refused ? "refused" : ""}`} style={style}>
            <div className="avatar" style={agentVars(e.agent)}>
              {meta.initials}
            </div>
            <span className="arrow">→</span>
            <div className="avatar" style={agentVars(to)}>
              {agentMeta(to).initials}
            </div>
            <span className="q" title={q}>
              {refused ? `refused: ${e.error}` : q}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (e.event === "agent_started" || e.event === "agent_finished") {
    if (e.event === "agent_finished" && e.text) {
      return (
        <div className={`ev ${depthClass}`} style={style}>
          <div className="avatar" style={style}>
            {meta.initials}
          </div>
          <div className="body">
            <div className="line1">
              <span className="agent">{meta.label}</span>
              <span className="time">{clock(e.recorded_at)}</span>
            </div>
            <div className="say">{e.text}</div>
          </div>
        </div>
      );
    }
    return null;
  }

  if (e.event === "tool_call") {
    if (e.tool_name === "final_result" || e.tool_name === "ask_teammate") return null;
    return (
      <div className={`ev ${depthClass}`} style={style}>
        <div className="body">
          <div className="tool">
            <span className="tname">{e.tool_name}</span>
            <span className="targs">{shortArgs(e.tool_args)}</span>
          </div>
        </div>
      </div>
    );
  }

  if (e.event === "tool_result") {
    if (e.tool_name === "final_result" || e.tool_name === "ask_teammate") return null;
    const refused = isRefusal(e.tool_result);
    return (
      <div className={`ev ${depthClass}`} style={style}>
        <div className="body">
          <div className={`tool ${refused ? "refusal" : "result"}`}>
            <span className="tname">{refused ? "refused" : "↳"}</span>
            <span className="targs">{resultGist(e.tool_result)}</span>
          </div>
        </div>
      </div>
    );
  }

  if (e.event === "model_response" && e.text) {
    return (
      <div className={`ev ${depthClass}`} style={style}>
        <div className="avatar" style={style}>
          {meta.initials}
        </div>
        <div className="body">
          <div className="line1">
            <span className="agent">{meta.label}</span>
            <span className="time">{clock(e.recorded_at)}</span>
          </div>
          <div className="say">{e.text}</div>
        </div>
      </div>
    );
  }

  return null;
}

export function Feed({
  events,
  running,
  selectedTicket,
}: {
  events: AgentEvent[];
  running: boolean;
  selectedTicket: number | null;
}) {
  if (!events.length) {
    return (
      <div className="empty">
        <span className="big">🗂</span>
        {selectedTicket
          ? `Ticket #${selectedTicket} is picked up. Press “Run the team” and watch them work.`
          : "Pick a ticket from the board to put the team on it."}
      </div>
    );
  }
  return (
    <div className="feed">
      {events.map((e) => (
        <EventRow key={`${e.run_id}-${e.seq}`} e={e} />
      ))}
      {running && <div className="milestone">⋯ working</div>}
    </div>
  );
}

/* --------------------------- the shift report ---------------------------- */

export function ShiftReport({ run, events }: { run: RunState; events: AgentEvent[] }) {
  const decision = run.result?.decision ?? null;
  const usage = run.result?.usage ?? null;

  const agentsInvolved = AGENT_ORDER.filter((a) => events.some((e) => e.agent === a));

  return (
    <div className="report">
      {decision && (
        <div className="verdict">
          <div className="vhead">
            <div className="avatar" style={agentVars("boss")}>
              BO
            </div>
            <h3>The boss’s call</h3>
            <span className={`status ${decision.outcome}`} style={{ position: "static" }}>
              {decision.outcome.replace(/_/g, " ")}
            </span>
          </div>
          <p>{decision.summary}</p>
          {decision.actions_taken.length > 0 && (
            <>
              <div className="colhead">
                <h2>What was written to the shop</h2>
              </div>
              <ul>
                {decision.actions_taken.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </>
          )}
          {decision.waiting_on_human.length > 0 && (
            <>
              <div className="colhead">
                <h2>Waiting on you</h2>
              </div>
              <ul>
                {decision.waiting_on_human.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </>
          )}
          <div className="next">
            <b>Next step:</b> {decision.next_step}
          </div>
        </div>
      )}

      {agentsInvolved.map((key) => {
        const meta = agentMeta(key);
        const mine = events.filter((e) => e.agent === key);
        const tools = mine
          .filter((e) => e.event === "tool_call" && e.tool_name !== "final_result")
          .map((e) => e.tool_name)
          .filter((t): t is string => Boolean(t) && t !== "ask_teammate");
        const uniqueTools = Array.from(new Set(tools));
        const said = [...mine].reverse().find((e) => e.text)?.text ?? "";
        const askedWho = mine
          .filter((e) => e.event === "delegation")
          .map((e) => agentMeta(String(e.tool_args?.teammate ?? "")).label);

        return (
          <div className="who-did" key={key} style={agentVars(key)}>
            <div className="avatar" style={agentVars(key)}>
              {meta.initials}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="line1">
                <span className="agent">{meta.label}</span>
                {askedWho.length > 0 && (
                  <span className="chip">asked {askedWho.join(", ")}</span>
                )}
              </div>
              <div className="did">
                {said.split("\n").slice(0, 4).join(" · ") || "—"}
              </div>
              {uniqueTools.length > 0 && (
                <div className="tools">
                  {uniqueTools.map((t) => (
                    <span className="chip" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {usage && (
        <div className="usage">
          <span>{usage.requests ?? 0} model calls</span>
          <span>{usage.tool_calls ?? 0} tool calls</span>
          <span>{(usage.total_tokens ?? 0).toLocaleString()} tokens</span>
          <span>{run.result?.model}</span>
        </div>
      )}
    </div>
  );
}
