/**
 * Every call the desk makes to the Campus Customs backend.
 *
 * The backend is the only thing this app talks to -- it never reaches the database or the
 * MCP server directly, so what the dashboard shows is exactly what the agents saw.
 */
import type {
  ApprovalsResponse,
  Cash,
  Draft,
  EventsResponse,
  PurchaseOrder,
  RunState,
  TicketsResponse,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on GET ${path}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const payload = await res.json();
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<{ ok: boolean; model: string; shop_today: string }>("/health"),

  tickets: () => get<TicketsResponse>("/tickets"),

  runTicket: (ticketId: number, approver: string) =>
    post<RunState>(`/tickets/${ticketId}/run`, { approver, wait: false }),

  run: (runId: string) => get<RunState>(`/runs/${runId}`),

  runs: () => get<{ count: number; runs: RunState[] }>("/runs"),

  /** Incremental poll: pass the last seq seen so the feed only pulls what is new. */
  events: (runId: string, afterSeq?: number) =>
    get<EventsResponse>(
      `/events?run_id=${encodeURIComponent(runId)}&limit=500` +
        (afterSeq !== undefined ? `&after_seq=${afterSeq}` : "")
    ),

  /** History straight from the append-only audit trail, so it survives a backend restart. */
  eventsForTicket: (ticketId: number) =>
    get<EventsResponse>(`/events?ticket_id=${ticketId}&limit=500`),

  approvals: () => get<ApprovalsResponse>("/approvals"),

  decideApproval: (approvalId: number, decision: "approved" | "denied", decidedBy: string) =>
    post<{
      approval_id: number;
      decision: string;
      decided_by: string;
      paid: boolean;
      payment: { ok: boolean; amount?: number; balance_after?: number; message?: string } | null;
      cash_after: number | null;
      refused_reason: string | null;
    }>(`/approvals/${approvalId}/decide`, { decision, decided_by: decidedBy }),

  cash: () => get<Cash>("/cash"),

  drafts: () => get<{ count: number; drafts: Draft[] }>("/drafts"),

  purchaseOrders: () =>
    get<{ count: number; purchase_orders: PurchaseOrder[] }>("/purchase-orders"),

  reset: () =>
    post<{ ok: boolean; message: string; open_tickets: number; cash: number }>("/reset"),
};
