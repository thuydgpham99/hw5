/**
 * Campus Customs — Operations Desk.
 *
 * Three columns, matching how the work actually moves: the board on the left (what came
 * in), the floor in the middle (the team working it), your desk on the right (what needs
 * a person). The cash readout sits in the top bar because it is the constraint every
 * decision on this screen runs into.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { money } from "./agents";
import { Board } from "./components/Board";
import { AgentRail, Feed, ShiftReport } from "./components/Feed";
import { Approvals, Drafts } from "./components/Desk";
import type { AgentEvent, Approval, Cash, Draft, RunState, Ticket } from "./types";

const APPROVER = "Jennifer Pham";
const POLL_MS = 1200;

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [shopToday, setShopToday] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [online, setOnline] = useState<boolean>(true);

  // #ticket=101 deep-links straight to a ticket, which also makes the board screenshotable.
  const hashTicket = (() => {
    const m = /#ticket=(\d+)/.exec(window.location.hash);
    return m ? Number(m[1]) : null;
  })();
  const [selectedId, setSelectedId] = useState<number | null>(hashTicket);
  const [run, setRun] = useState<RunState | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [tab, setTab] = useState<"feed" | "report">("feed");

  const [cash, setCash] = useState<Cash | null>(null);
  const [cashDropped, setCashDropped] = useState(false);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const prevBalance = useRef<number | null>(null);
  const feedEnd = useRef<HTMLDivElement | null>(null);

  const running = run?.status === "running" || run?.status === "queued" || run?.status === "started";

  /* ----------------------------- loading shop state ----------------------------- */

  const refreshShop = useCallback(async () => {
    try {
      const [t, c, a, d] = await Promise.all([
        api.tickets(),
        api.cash(),
        api.approvals(),
        api.drafts(),
      ]);
      setTickets(t.tickets.slice().sort((x, y) => x.id - y.id));
      setShopToday(t.shop_today);
      setApprovals(a.approvals);
      setDrafts(d.drafts);
      setCash((old) => {
        if (old && c.balance < old.balance) {
          setCashDropped(true);
          window.setTimeout(() => setCashDropped(false), 1600);
        }
        prevBalance.current = c.balance;
        return c;
      });
      setOnline(true);
    } catch (e) {
      setOnline(false);
      setError(
        `Cannot reach the backend. Start it with: cd backend && uvicorn main:app --reload --port 8000`
      );
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then((h) => setModel(h.model))
      .catch(() => setOnline(false));
    refreshShop();
  }, [refreshShop]);

  /* ------------------------------- polling a run -------------------------------- */

  useEffect(() => {
    if (!run || !running) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const latest = events.length ? events[events.length - 1].seq : undefined;
        const [state, fresh] = await Promise.all([
          api.run(run.run_id),
          api.events(run.run_id, latest),
        ]);
        if (cancelled) return;
        if (fresh.events.length) setEvents((prev) => [...prev, ...fresh.events]);
        setRun(state);
        if (state.status === "finished" || state.status === "failed") {
          setTab("report");
          refreshShop();
        }
      } catch {
        /* a dropped poll is not fatal; the next tick retries */
      }
    };

    const id = window.setInterval(tick, POLL_MS);
    tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [run, running, events, refreshShop]);

  useEffect(() => {
    if (tab === "feed") feedEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, tab]);

  /* Selecting a ticket with no run in flight pulls up the last shift worked on it, so the
     board is a record of what happened rather than only a live view. */
  const loadLastRun = useCallback(
    async (ticketId: number) => {
      try {
        const all = await api.runs();
        const mine = all.runs.filter((r) => r.ticket_id === ticketId);
        const last = mine[mine.length - 1];
        if (last) {
          const ev = await api.events(last.run_id);
          setRun(last);
          setEvents(ev.events);
          setTab(last.result?.decision ? "report" : "feed");
          return;
        }
        // The server only remembers runs from its current process; the audit trail remembers
        // all of them. Fall back to it so history survives a restart.
        const trail = await api.eventsForTicket(ticketId);
        if (!trail.events.length) {
          setRun(null);
          setEvents([]);
          return;
        }
        const lastRunId = trail.events[trail.events.length - 1].run_id;
        setEvents(trail.events.filter((e) => e.run_id === lastRunId));
        setRun({
          run_id: lastRunId,
          ticket_id: ticketId,
          status: "finished",
          result: null,
          error: null,
        });
        setTab("feed");
      } catch {
        /* history is a nicety; a failure here must not break the desk */
      }
    },
    []
  );

  useEffect(() => {
    if (selectedId !== null && !running) void loadLastRun(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tickets.length]);

  /* --------------------------------- actions ----------------------------------- */

  const startRun = async (ticketId: number) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    setEvents([]);
    setTab("feed");
    try {
      const started = await api.runTicket(ticketId, APPROVER);
      setRun({ ...started, status: "running", result: null, error: null });
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approvalId: number, decision: "approved" | "denied") => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.decideApproval(approvalId, decision, APPROVER);
      if (res.paid && res.payment?.ok) {
        setNotice(
          `Paid ${money(res.payment.amount ?? 0)} — checking is now ${money(
            res.payment.balance_after ?? 0
          )}.`
        );
      } else if (res.refused_reason) {
        setError(res.refused_reason);
      } else {
        setNotice(`Approval #${approvalId} ${decision}.`);
      }
      await refreshShop();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const resetAll = async () => {
    setBusy(true);
    try {
      const r = await api.reset();
      setRun(null);
      setEvents([]);
      setSelectedId(null);
      setNotice(`Fresh start — ${r.open_tickets} open tickets, ${money(r.cash)} in checking.`);
      await refreshShop();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  /* --------------------------------- derived ----------------------------------- */

  const activeAgent = useMemo(() => {
    if (!running) return null;
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.agent && e.agent !== "human") return e.agent;
    }
    return "boss";
  }, [events, running]);

  const pendingCount = approvals.filter((a) => a.status === "pending").length;
  const committed = cash?.committed_to_pending_approvals ?? 0;
  const barPct = cash && cash.balance > 0 ? Math.min(100, (committed / cash.balance) * 100) : 0;
  const selectedTicket = tickets.find((t) => t.id === selectedId) ?? null;
  const ticketDrafts = selectedId ? drafts.filter((d) => d.ticket_id === selectedId) : drafts;

  return (
    <div className="desk">
      {/* ------------------------------- top bar ------------------------------- */}
      <div className="topbar">
        <div className="brand">
          <h1>Campus Customs</h1>
          <span className="sub">operations desk</span>
        </div>
        {shopToday && <span className="pill clock">⏱ shop today {shopToday}</span>}
        {model && <span className="pill model">{model}</span>}
        {!online && <span className="pill offline">backend offline</span>}

        <div className="spacer" />

        <div className="cash">
          <div>
            <div className="label">checking</div>
            <div className={`amount ${cashDropped ? "dropped" : ""}`}>
              {money(cash?.balance ?? null)}
            </div>
          </div>
          <div>
            <div className="bar">
              <span style={{ width: `${barPct}%` }} />
            </div>
            <div className="committed">
              {money(committed)} committed · {money(cash?.uncommitted ?? 0)} free
            </div>
          </div>
        </div>

        <button className="btn ghost" onClick={resetAll} disabled={busy || running}>
          Fresh start
        </button>
      </div>

      {/* -------------------------------- floor -------------------------------- */}
      <div className="floor">
        {/* column 1 — the board */}
        <div className="col">
          <div className="colhead">
            <h2>The board</h2>
            <span className="note">{tickets.filter((t) => t.is_open).length} open</span>
          </div>
          <Board
            tickets={tickets}
            selectedId={selectedId}
            runningTicketId={running ? run?.ticket_id ?? null : null}
            onSelect={setSelectedId}
            onRun={startRun}
            busy={busy || running}
          />
          {error && <div className="banner err">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}
        </div>

        {/* column 2 — the floor */}
        <div className="col">
          <div className="colhead">
            <h2>The floor</h2>
            <span className="note">
              {running
                ? "team is working"
                : run?.status === "finished"
                ? "shift complete"
                : "five agents, fully connected"}
            </span>
          </div>

          <AgentRail events={events} activeAgent={activeAgent} />

          <div className="panel">
            <div className="tabs">
              <button
                aria-selected={tab === "feed"}
                onClick={() => setTab("feed")}
              >
                Live feed<span className="count">{events.length}</span>
              </button>
              <button
                aria-selected={tab === "report"}
                onClick={() => setTab("report")}
                disabled={!run?.result}
              >
                Shift report
              </button>
            </div>

            {tab === "feed" ? (
              <>
                <Feed events={events} running={running} selectedTicket={selectedId} />
                <div ref={feedEnd} />
              </>
            ) : run ? (
              <ShiftReport run={run} events={events} />
            ) : null}
          </div>
        </div>

        {/* column 3 — your desk */}
        <div className="col col-desk">
          <div className="colhead">
            <h2>Your desk</h2>
            <span className="note">
              {pendingCount ? `${pendingCount} need your signature` : "all clear"}
            </span>
          </div>
          <Approvals approvals={approvals} onDecide={decide} busy={busy} />

          {ticketDrafts.length > 0 && (
            <>
              <div className="colhead">
                <h2>Drafts on the board</h2>
                <span className="note">yours to send</span>
              </div>
              <Drafts drafts={ticketDrafts} />
            </>
          )}
        </div>
      </div>

      <div className="foot">
        {selectedTicket
          ? `ticket #${selectedTicket.id} · ${selectedTicket.status}`
          : "no ticket selected"}
        {"  ·  "}agents prepare, a human approves, only then does cash move
      </div>
    </div>
  );
}
