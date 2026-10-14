export type AgentName =
  | "boss"
  | "inventory"
  | "accounting"
  | "facilities"
  | "customer_service"
  | "human";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: string;
  notes: string | null;
  created_at: string;
  is_open: boolean;
  is_resolved: boolean;
}

export interface TicketsResponse {
  shop_today: string;
  count: number;
  open_count: number;
  tickets: Ticket[];
}

export type AuditEvent =
  | "run_started"
  | "agent_started"
  | "model_response"
  | "tool_call"
  | "tool_result"
  | "delegation"
  | "delegation_refused"
  | "agent_finished"
  | "agent_error"
  | "human_decision"
  | "payment_executed"
  | "run_finished";

export interface AgentEvent {
  run_id: string;
  seq: number;
  recorded_at: string;
  ticket_id: number | null;
  agent: AgentName | string;
  event: AuditEvent;
  depth: number;
  chain: string[];
  model: string | null;
  summary: string;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: unknown;
  text: string | null;
  usage: Record<string, number | null> | null;
  error: string | null;
}

export interface EventsResponse {
  count: number;
  total_in_trail: number;
  latest_seq: number | null;
  events: AgentEvent[];
}

export interface TicketDecision {
  ticket_id: number;
  outcome: "resolved" | "awaiting_approval" | "blocked" | "cancelled";
  summary: string;
  consulted: string[];
  actions_taken: string[];
  waiting_on_human: string[];
  next_step: string;
}

export interface RunResult {
  run_id: string;
  ticket_id: number;
  model: string;
  decision: TicketDecision | null;
  error: string | null;
  usage: Record<string, number | null>;
  delegations: Record<string, number>;
}

export interface RunState {
  run_id: string;
  ticket_id: number;
  status: "queued" | "running" | "finished" | "failed" | "started";
  result: RunResult | null;
  error: string | null;
  poll?: string;
}

export interface Approval {
  id: number;
  ticket_id: number | null;
  kind: string;
  ref_id: number | null;
  amount: number;
  account: string;
  reason: string;
  status: "pending" | "approved" | "denied" | "paid";
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  payment_id: number | null;
}

export interface ApprovalsResponse {
  count: number;
  pending_count: number;
  approvals: Approval[];
}

export interface Cash {
  found: boolean;
  name: string;
  balance: number;
  date: string;
  shop_today: string;
  committed_to_pending_approvals: number;
  uncommitted: number;
  note: string;
}

export interface Draft {
  id: number;
  ticket_id: number;
  audience: string;
  subject: string;
  body: string;
  drafted_by: string;
  created_at: string;
}

export interface PurchaseOrder {
  id: number;
  ticket_id: number | null;
  vendor_id: number;
  sku: string;
  size: string;
  qty: number;
  unit_cost: number;
  total_cost: number;
  status: string;
  expected_arrival: string | null;
  created_by: string;
  created_at: string;
}
