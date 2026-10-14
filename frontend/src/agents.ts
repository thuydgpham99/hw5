/** Who the five agents are, and how each one reads on the board. */

export interface AgentMeta {
  key: string;
  label: string;
  initials: string;
  role: string;
  /** Drives the agent's colour everywhere it appears: rail, avatar, feed stripe. */
  hue: number;
}

export const AGENTS: Record<string, AgentMeta> = {
  boss: {
    key: "boss",
    label: "Boss",
    initials: "BO",
    role: "routes the ticket, makes the final call",
    hue: 262,
  },
  inventory: {
    key: "inventory",
    label: "Inventory",
    initials: "IN",
    role: "stock by size, shortfalls, restock options",
    hue: 158,
  },
  accounting: {
    key: "accounting",
    label: "Accounting",
    initials: "AC",
    role: "cash, invoices, margins, payment requests",
    hue: 38,
  },
  facilities: {
    key: "facilities",
    label: "Facilities",
    initials: "FA",
    role: "the lease, rent, the landlord",
    hue: 199,
  },
  customer_service: {
    key: "customer_service",
    label: "Customer Service",
    initials: "CS",
    role: "drafts what the shop says back",
    hue: 330,
  },
  human: {
    key: "human",
    label: "You",
    initials: "YOU",
    role: "approves the money",
    hue: 0,
  },
};

export const AGENT_ORDER = [
  "boss",
  "inventory",
  "accounting",
  "facilities",
  "customer_service",
];

export function agentMeta(key: string): AgentMeta {
  return (
    AGENTS[key] ?? {
      key,
      label: key,
      initials: key.slice(0, 2).toUpperCase(),
      role: "",
      hue: 220,
    }
  );
}

/** Inline custom properties so one hue drives every colour an agent uses. */
export function agentVars(key: string): React.CSSProperties {
  const { hue } = agentMeta(key);
  return { ["--h" as string]: String(hue) } as React.CSSProperties;
}

export const money = (n: number | null | undefined): string =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD" });
