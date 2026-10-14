/**
 * Your side of the desk: the approvals that need a signature, and the drafts the team
 * left for you to send.
 *
 * Approvals are rendered as paper slips on a dark desk, because they are the one thing on
 * this screen that a person -- not an agent -- has to act on.
 */
import { agentMeta, money } from "../agents";
import type { Approval, Draft } from "../types";

const KIND_LABEL: Record<string, string> = {
  invoice: "pay vendor invoice",
  rent: "pay rent",
  purchase_order: "purchase order",
};

export function ApprovalSlip({
  approval,
  onDecide,
  busy,
}: {
  approval: Approval;
  onDecide: (id: number, decision: "approved" | "denied") => void;
  busy: boolean;
}) {
  const pending = approval.status === "pending";
  const requester = agentMeta(approval.requested_by);

  return (
    <div className={`slip ${pending ? "" : "settled"}`}>
      {approval.status === "paid" && <div className="paid-stamp">PAID</div>}
      {approval.status === "denied" && <div className="paid-stamp denied">DENIED</div>}
      {approval.status === "approved" && <div className="paid-stamp">APPROVED</div>}

      <div className="kind">{KIND_LABEL[approval.kind] ?? approval.kind}</div>
      <div className="amt">{money(approval.amount)}</div>
      <div className="why">{approval.reason}</div>

      <div className="meta">
        requested by {requester.label.toLowerCase()} · {approval.account} ·{" "}
        {approval.kind} #{approval.ref_id}
        {approval.ticket_id ? ` · ticket ${approval.ticket_id}` : ""}
        {approval.decided_by ? ` · signed ${approval.decided_by}` : ""}
      </div>

      {pending && (
        <div className="acts">
          <button
            className="approve"
            disabled={busy}
            onClick={() => onDecide(approval.id, "approved")}
          >
            Approve &amp; pay
          </button>
          <button
            className="deny"
            disabled={busy}
            onClick={() => onDecide(approval.id, "denied")}
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}

export function Approvals({
  approvals,
  onDecide,
  busy,
}: {
  approvals: Approval[];
  onDecide: (id: number, decision: "approved" | "denied") => void;
  busy: boolean;
}) {
  const pending = approvals.filter((a) => a.status === "pending");
  const settled = approvals.filter((a) => a.status !== "pending");

  if (!approvals.length) {
    return (
      <div className="empty">
        <span className="big">🖊</span>
        Nothing needs your signature yet.
        <br />
        Agents can only ask — they can never pay.
      </div>
    );
  }

  return (
    <>
      {pending.map((a) => (
        <ApprovalSlip key={a.id} approval={a} onDecide={onDecide} busy={busy} />
      ))}
      {settled.map((a) => (
        <ApprovalSlip key={a.id} approval={a} onDecide={onDecide} busy={busy} />
      ))}
    </>
  );
}

export function Drafts({ drafts }: { drafts: Draft[] }) {
  if (!drafts.length) return null;
  return (
    <>
      {drafts.map((d) => (
        <div className="draft" key={d.id}>
          <div className="to">
            to {d.audience} · ticket {d.ticket_id} · by {agentMeta(d.drafted_by).label}
          </div>
          <h4>{d.subject}</h4>
          <p>{d.body}</p>
          <span className="unsent">NOT SENT — YOURS TO SEND</span>
        </div>
      ))}
    </>
  );
}
