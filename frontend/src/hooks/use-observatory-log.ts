"use client";

import { useEffect, useRef, useState } from "react";

import { AGENTS, type AgentId } from "@/lib/design/agents";
import { GRADE_LABEL, num } from "@/lib/scores";
import { emitUniverseEvent, setUniverseActivity } from "@/lib/universe-events";
import type { DiscoveredToken } from "@/types/api";
import type { TokenScore } from "@/types/score";

/**
 * OBSERVATORY LOG
 *
 * A chronological record of what the division actually did. Every entry is
 * generated from a real state transition — a token appearing in the stream, the
 * scoring engine reporting on it, the risk gate vetoing it, Apex certifying it.
 *
 * The verdicts are the backend's. Each line is attributed to the agent named in
 * the API's reason code and worded with the message the API rendered, so the log
 * cannot claim something the engine did not conclude. These lines used to be
 * composed on the client from local thresholds, which meant the log and the
 * score could disagree about the same token.
 *
 * This hook is also where universe reactions originate, because the same
 * transitions drive both: one traversal, two outputs.
 */

/**
 * What kind of event a line records.
 *
 * Grouping exists so the log can be read for one concern at a time — "what did
 * the risk gate do" is a different question from "what arrived" — without
 * splitting it into separate feeds that would each lose the chronology.
 */
export type LogCategory = "discovery" | "risk" | "market" | "ai" | "infrastructure";

export type LogSeverity = "info" | "positive" | "caution" | "critical";

export interface LogEntry {
  id: string;
  at: Date;
  agent: AgentId;
  category: LogCategory;
  severity: LogSeverity;
  message: string;
  mint: string;
  /** Elite entries are the only ones permitted gold. */
  elite?: boolean;
}

export const LOG_CATEGORY_LABEL: Record<LogCategory, string> = {
  discovery: "Discovery",
  risk: "Risk",
  market: "Market",
  ai: "AI",
  infrastructure: "Infrastructure",
};

const MAX_ENTRIES = 60;

/** Agents the log can attribute to, so an unknown value never breaks styling. */
const KNOWN_AGENTS = new Set<string>(Object.keys(AGENTS));

/** The ends of the grade ladder — conviction and danger. See the filter below. */
const NOTABLE_GRADES = new Set<string>(["strong", "high_conviction", "critical"]);

function agentIdOf(value: string | undefined, fallback: AgentId): AgentId {
  return value && KNOWN_AGENTS.has(value) ? (value as AgentId) : fallback;
}

/** Last-resort name lookup for a scored mint the ranking response did not name. */
function nameFromFeed(tokens: DiscoveredToken[], mint: string): string | undefined {
  const token = tokens.find((candidate) => candidate.mint_address === mint);
  return token?.symbol ?? token?.name ?? undefined;
}

export function useObservatoryLog(
  tokens: DiscoveredToken[],
  scoresByMint: Map<string, TokenScore>,
  labelsByMint?: Map<string, string>,
) {
  const [entries, setEntries] = useState<LogEntry[]>([]);

  // What we have already reported on, so a re-render never duplicates a line.
  const seenTokens = useRef(new Set<string>());
  const seenScores = useRef(new Set<string>());
  const seenElite = useRef(new Set<string>());
  const seenVeto = useRef(new Set<string>());
  const primed = useRef(false);

  useEffect(() => {
    const fresh: LogEntry[] = [];
    const now = new Date();

    // First pass seeds the "already seen" sets from the REST backfill without
    // logging it — otherwise landing on the page would dump sixty historical
    // discoveries into a live feed and bury whatever happens next.
    const silent = !primed.current;

    // --- Arrivals, from the discovery feed -------------------------------
    for (const token of tokens) {
      const mint = token.mint_address;
      const name = token.symbol ?? token.name ?? "unidentified";

      if (!seenTokens.current.has(mint)) {
        seenTokens.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-scout`,
            at: now,
            agent: "scout",
            category: "discovery",
            severity: "info",
            message: `New signal detected — ${name}.`,
            mint,
          });
          emitUniverseEvent("discovery", name);
        }
      }
    }

    // --- Verdicts, from the scoring window --------------------------------
    //
    // Deliberately a separate pass over `scoresByMint` rather than a lookup
    // inside the loop above. Joining on the discovery feed meant a verdict was
    // only ever reported if the engine happened to score a token while it was
    // still among the newest forty arrivals — and at the rate the scanner
    // discovers, most tokens fall out of that window before their first
    // evaluation lands. The result was a log that recorded arrivals and almost
    // nothing else, despite the station having a hundred fresh verdicts in
    // hand. The scoring window is the correct source for what the engine
    // decided; the feed is the correct source for what arrived.
    for (const [mint, score] of scoresByMint) {
      const name =
        labelsByMint?.get(mint) ??
        nameFromFeed(tokens, mint) ??
        `${mint.slice(0, 4)}…${mint.slice(-4)}`;

      // The engine's own verdict for this token.
      //
      // This branch used to look only at `score.reasons`, which the ranking
      // endpoint never populates — a list is scanned, not read, so the
      // breakdown is omitted. The result was a branch that could not fire: the
      // engine's verdict never reached the log at all. It now falls back to
      // `grade`, which is the backend's own categorical decision and is always
      // present, and still prefers a rendered reason if one ever arrives.
      //
      // Only the ends of the ladder earn a line. Weak and Watch are the bulk of
      // the feed and would bury everything else — a legibility filter over
      // backend verdicts, not a judgement about any token.
      if (!seenScores.current.has(mint)) {
        seenScores.current.add(mint);
        const headline = score.reasons.find(
          (reason) => reason.severity === "positive" || reason.severity === "caution",
        );
        const notable = NOTABLE_GRADES.has(score.grade);

        if (!silent && (headline || notable)) {
          fresh.push({
            id: `${mint}-${headline?.code ?? score.grade}`,
            at: now,
            agent: agentIdOf(headline?.agent, "oracle"),
            category: "ai",
            severity:
              headline?.severity ?? (score.grade === "critical" ? "caution" : "positive"),
            message: headline
              ? `${headline.message} — ${name}.`
              : `Graded ${GRADE_LABEL[score.grade]} — ${name}.`,
            mint,
          });
        }
      }

      // A veto is the single most important thing the division can report.
      if (score.risk.has_veto && !seenVeto.current.has(mint)) {
        seenVeto.current.add(mint);
        if (!silent) {
          const critical = score.reasons.find((reason) => reason.severity === "critical");
          fresh.push({
            id: `${mint}-veto`,
            at: now,
            agent: agentIdOf(critical?.agent, "sentinel"),
            category: "risk",
            severity: "critical",
            message: `${critical?.message ?? "Risk gate engaged — score capped."} — ${name}.`,
            mint,
          });
          emitUniverseEvent("threat", name);
        }
      }

      if (score.is_elite && !seenElite.current.has(mint)) {
        seenElite.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-apex`,
            at: now,
            agent: "apex",
            category: "ai",
            severity: "positive",
            message: `Elite classification granted — ${name}.`,
            mint,
            elite: true,
          });
          emitUniverseEvent("elite", name);
        }
      }
    }

    primed.current = true;

    // Activity drives particle and data-stream density in the background.
    // Scoring coverage is a fair proxy for how busy the chain is.
    const coverage = tokens.length > 0 ? scoresByMint.size / Math.max(tokens.length, 1) : 0;
    setUniverseActivity(0.2 + Math.min(1, coverage) * 0.8);

    if (fresh.length > 0) {
      setEntries((current) => [...fresh.reverse(), ...current].slice(0, MAX_ENTRIES));
    }
  }, [tokens, scoresByMint, labelsByMint]);

  return entries;
}

export function agentOf(entry: LogEntry) {
  return AGENTS[entry.agent];
}

/** Aggregate conviction across the scored window, for the Core. 0–1. */
export function averageConfidence(scores: Map<string, TokenScore>): number {
  if (scores.size === 0) return 0;
  let total = 0;
  for (const score of scores.values()) total += num(score.evidence.confidence);
  return total / scores.size / 100;
}
