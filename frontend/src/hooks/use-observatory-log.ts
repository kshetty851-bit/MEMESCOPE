"use client";

import { useEffect, useRef, useState } from "react";

import { AGENTS, type AgentId } from "@/lib/design/agents";
import { deriveIntelligence } from "@/lib/intelligence";
import { emitUniverseEvent, setUniverseActivity } from "@/lib/universe-events";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";

/**
 * OBSERVATORY LOG
 *
 * A chronological record of what the division actually did. Every entry is
 * generated from a real state transition — a token appearing in the stream, a
 * market observation arriving, a score crossing a threshold. Nothing is
 * invented and nothing is emitted on a timer, so an idle log means an idle
 * chain rather than a broken feed.
 *
 * This hook is also where universe reactions originate, because the same
 * transitions drive both: one traversal, two outputs.
 */

export interface LogEntry {
  id: string;
  at: Date;
  agent: AgentId;
  message: string;
  mint: string;
  /** Elite entries are the only ones permitted gold. */
  elite?: boolean;
}

const MAX_ENTRIES = 60;

export function useObservatoryLog(
  tokens: DiscoveredToken[],
  byMint: Map<string, MarketSnapshot>,
) {
  const [entries, setEntries] = useState<LogEntry[]>([]);

  // What we have already reported on, so a re-render never duplicates a line.
  const seenTokens = useRef(new Set<string>());
  const seenMarkets = useRef(new Set<string>());
  const seenElite = useRef(new Set<string>());
  const seenWhale = useRef(new Set<string>());
  const seenThreat = useRef(new Set<string>());
  const seenCleared = useRef(new Set<string>());
  const primed = useRef(false);

  useEffect(() => {
    const fresh: LogEntry[] = [];
    const now = new Date();

    // First pass seeds the "already seen" sets from the REST backfill without
    // logging it — otherwise landing on the page would dump sixty historical
    // discoveries into a live feed and bury whatever happens next.
    const silent = !primed.current;

    for (const token of tokens) {
      const mint = token.mint_address;
      const market = byMint.get(mint) ?? null;
      const intel = deriveIntelligence(token, market);
      const name = token.symbol ?? token.name ?? "unidentified";

      if (!seenTokens.current.has(mint)) {
        seenTokens.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-scout`,
            at: now,
            agent: "scout",
            message: `New signal detected — ${name}.`,
            mint,
          });
          emitUniverseEvent("discovery", name);
        }
      }

      // Oracle reports only notable conviction. Logging every scored token
      // would emit ~100 lines on each market refresh and bury the events that
      // actually matter — the log becomes a scrollback of noise rather than a
      // narrative.
      if (market && !seenMarkets.current.has(mint)) {
        seenMarkets.current.add(mint);
        if (!silent && intel.confidence >= 0.6) {
          fresh.push({
            id: `${mint}-oracle`,
            at: now,
            agent: "oracle",
            message: `Confidence exceeds baseline at ${Math.round(intel.confidence * 100)}% — ${name}.`,
            mint,
          });
        }
      }

      // Sentinel confirms a clean review once, for tokens that clear it well.
      if (
        market &&
        intel.risk.score < 0.2 &&
        !seenCleared.current.has(mint) &&
        seenMarkets.current.has(mint)
      ) {
        seenCleared.current.add(mint);
        if (!silent && intel.confidence >= 0.55) {
          fresh.push({
            id: `${mint}-cleared`,
            at: now,
            agent: "sentinel",
            message: `No contract anomalies — ${name}.`,
            mint,
          });
        }
      }

      if (market && intel.whale.score >= 0.7 && !seenWhale.current.has(mint)) {
        seenWhale.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-titan`,
            at: now,
            agent: "titan",
            message: `Whale accumulation confirmed — ${name}.`,
            mint,
          });
          emitUniverseEvent("whale", name);
        }
      }

      if (market && intel.risk.score >= 0.7 && !seenThreat.current.has(mint)) {
        seenThreat.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-sentinel`,
            at: now,
            agent: "sentinel",
            message: `Security concerns detected — ${name}.`,
            mint,
          });
          emitUniverseEvent("threat", name);
        }
      }

      if (intel.elite && !seenElite.current.has(mint)) {
        seenElite.current.add(mint);
        if (!silent) {
          fresh.push({
            id: `${mint}-apex`,
            at: now,
            agent: "apex",
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
    // Enrichment coverage is a fair proxy for how busy the chain is.
    const coverage = tokens.length > 0 ? byMint.size / Math.max(tokens.length, 1) : 0;
    setUniverseActivity(0.2 + coverage * 0.8);

    if (fresh.length > 0) {
      setEntries((current) => [...fresh.reverse(), ...current].slice(0, MAX_ENTRIES));
    }
  }, [tokens, byMint]);

  return entries;
}

export function agentOf(entry: LogEntry) {
  return AGENTS[entry.agent];
}
