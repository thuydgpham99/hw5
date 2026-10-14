/** The board: the three tickets, and the button that puts the team on one. */
import type { Ticket } from "../types";

const TYPE_LABEL: Record<string, string> = {
  customer_order: "customer order",
  rent_notice: "rent notice",
  price_override: "price request",
};

export function TicketCard({
  ticket,
  selected,
  running,
  onSelect,
  onRun,
  busy,
}: {
  ticket: Ticket;
  selected: boolean;
  running: boolean;
  onSelect: () => void;
  onRun: () => void;
  busy: boolean;
}) {
  const done = ticket.is_resolved;
  const status = running ? "running" : ticket.status;

  return (
    <div
      className={`ticket ${selected ? "selected" : ""} ${running ? "running" : ""} ${
        done ? "done" : ""
      }`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect()}
    >
      <span className={`status ${status}`}>{status.replace(/_/g, " ")}</span>
      <div className="tid">TICKET #{ticket.id}</div>
      <h3>{ticket.subject}</h3>
      <div className="who">{ticket.requester}</div>

      <div className="meta">
        <span className="chip">{TYPE_LABEL[ticket.type] ?? ticket.type}</span>
        {ticket.sku && (
          <span className="chip key">
            {ticket.sku}
            {ticket.size ? ` · ${ticket.size}` : ""}
            {ticket.qty ? ` × ${ticket.qty}` : ""}
          </span>
        )}
        {ticket.lease_id !== null && <span className="chip key">lease {ticket.lease_id}</span>}
        {ticket.invoice_id !== null && (
          <span className="chip key">invoice {ticket.invoice_id}</span>
        )}
      </div>

      {selected && (
        <div className="runbar">
          <button
            className="btn primary sm"
            disabled={busy || running}
            onClick={(e) => {
              e.stopPropagation();
              onRun();
            }}
          >
            {running ? "Team is working…" : done ? "Run the team again" : "Run the team"}
          </button>
        </div>
      )}

      {done && <div className="stamp">RESOLVED</div>}
    </div>
  );
}

export function Board({
  tickets,
  selectedId,
  runningTicketId,
  onSelect,
  onRun,
  busy,
}: {
  tickets: Ticket[];
  selectedId: number | null;
  runningTicketId: number | null;
  onSelect: (id: number) => void;
  onRun: (id: number) => void;
  busy: boolean;
}) {
  return (
    <>
      {tickets.map((t) => (
        <TicketCard
          key={t.id}
          ticket={t}
          selected={selectedId === t.id}
          running={runningTicketId === t.id}
          onSelect={() => onSelect(t.id)}
          onRun={() => onRun(t.id)}
          busy={busy}
        />
      ))}
    </>
  );
}
