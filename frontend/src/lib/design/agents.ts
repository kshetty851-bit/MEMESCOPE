/**
 * THE INTELLIGENCE DIVISION
 *
 * Seven specialists. Each owns one hue, one mission, one voice. The hue is the
 * identity carrier — a border, a dot or a glow is enough to say who is
 * speaking, which is what lets the interface stay quiet while still being
 * legible at a glance.
 *
 * Ordering is the intelligence pipeline, not alphabetical:
 * Scout finds it, Titan weighs it, Pulse times it, Echo listens, Sentinel
 * clears it, Oracle reasons over it, Apex certifies it.
 */

export type AgentId =
  | "scout"
  | "titan"
  | "pulse"
  | "echo"
  | "sentinel"
  | "oracle"
  | "apex";

/**
 * Each specialist's register. This is a contract, not flavour text: every
 * string a given agent emits anywhere in the product must sit inside its tone.
 * Nothing playful, nothing childish — these are analysts filing reports.
 */
export type AgentTone =
  | "explorer"
  | "protective"
  | "energetic"
  | "observant"
  | "guardian"
  | "scientific"
  | "authority";

export interface Agent {
  id: AgentId;
  name: string;
  /** One-line mission, used as the card subtitle. */
  mission: string;
  /** Three adjectives — the agent's personality, shown on the division page. */
  traits: [string, string, string];
  /** Register every utterance from this agent must obey. */
  tone: AgentTone;
  /** Canonical line, used as the dossier epigraph. */
  voice: string;
  /** CSS custom property name carrying the agent hue. */
  hue: string;
  /** Tailwind-facing token name, e.g. `text-scout`. */
  token: string;
  /** Position in the pipeline, 1-indexed. Apex sits outside it, at 0. */
  step: number;
}

export const AGENTS: Record<AgentId, Agent> = {
  scout: {
    id: "scout",
    name: "SCOUT",
    mission: "Discovers newly launched tokens",
    traits: ["Curious", "Fearless", "Relentless"],
    tone: "explorer",
    voice: "New signal detected.",
    hue: "var(--color-scout)",
    token: "scout",
    step: 1,
  },
  titan: {
    id: "titan",
    name: "TITAN",
    mission: "Tracks whale wallets and large flows",
    traits: ["Patient", "Powerful", "Protective"],
    tone: "protective",
    voice: "Large capital entering.",
    hue: "var(--color-titan)",
    token: "titan",
    step: 2,
  },
  pulse: {
    id: "pulse",
    name: "PULSE",
    mission: "Measures momentum and acceleration",
    traits: ["Fast", "Precise", "Unrelenting"],
    tone: "energetic",
    voice: "Acceleration detected.",
    hue: "var(--color-pulse)",
    token: "pulse",
    step: 3,
  },
  echo: {
    id: "echo",
    name: "ECHO",
    mission: "Reads narrative and social attention",
    traits: ["Adaptive", "Attuned", "Perceptive"],
    tone: "observant",
    voice: "Narrative expanding.",
    hue: "var(--color-echo)",
    token: "echo",
    step: 4,
  },
  sentinel: {
    id: "sentinel",
    name: "SENTINEL",
    mission: "Detects rugs, scams and hidden risk",
    traits: ["Silent", "Observant", "Unyielding"],
    tone: "guardian",
    voice: "No contract anomalies.",
    hue: "var(--color-sentinel)",
    token: "sentinel",
    step: 5,
  },
  oracle: {
    id: "oracle",
    name: "ORACLE",
    mission: "Reasons over evidence and scores confidence",
    traits: ["Rigorous", "Calm", "Exacting"],
    tone: "scientific",
    voice: "Confidence exceeds historical baseline.",
    hue: "var(--color-oracle)",
    token: "oracle",
    step: 6,
  },
  apex: {
    id: "apex",
    name: "APEX",
    mission: "Grants Elite classification",
    traits: ["Rare", "Absolute", "Final"],
    tone: "authority",
    voice: "Elite classification granted.",
    hue: "var(--color-apex)",
    token: "apex",
    step: 0,
  },
};

/** Pipeline order — the six analysts, ending at Oracle. Apex is excluded. */
export const PIPELINE: AgentId[] = [
  "scout",
  "titan",
  "pulse",
  "echo",
  "sentinel",
  "oracle",
];

export const ALL_AGENTS: AgentId[] = [...PIPELINE, "apex"];

export function agent(id: AgentId): Agent {
  return AGENTS[id];
}

/**
 * Operational status, shown beneath every sigil.
 *
 * Seven states, deliberately: enough to describe what a specialist is actually
 * doing, few enough that a user learns the whole vocabulary in one sitting.
 * All are present-tense verbs — the division is never "done".
 */
export type AgentStatus =
  | "monitoring"
  | "analysing"
  | "learning"
  | "investigating"
  | "alert"
  | "synchronising"
  | "idle";

export const STATUS_LABEL: Record<AgentStatus, string> = {
  monitoring: "Monitoring",
  analysing: "Analysing",
  learning: "Learning",
  investigating: "Investigating",
  alert: "Alert",
  synchronising: "Synchronising",
  idle: "Idle",
};

/** Only `alert` breaks the agent's own hue — it is the one state that must interrupt. */
export const STATUS_TONE: Record<AgentStatus, string | null> = {
  monitoring: null,
  analysing: null,
  learning: null,
  investigating: null,
  alert: "var(--color-danger)",
  synchronising: null,
  idle: "var(--color-ink-faint)",
};

/** A status that is not `idle` means the specialist is actively working. */
export function isActive(status: AgentStatus): boolean {
  return status !== "idle";
}
