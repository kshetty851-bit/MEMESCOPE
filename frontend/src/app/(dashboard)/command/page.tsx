"use client";

import { useEffect, useMemo, useState } from "react";

import { DashboardPrimer } from "@/components/alpha/dashboard-primer";
import { Mascot } from "@/components/brand/mascot";
import { MissionBrief } from "@/components/decision/mission-brief";
import { OpportunityQueue, type QueueItem } from "@/components/decision/opportunity-queue";
import { RadarScoreboard } from "@/components/decision/radar-scoreboard";
import { SinceLastVisit } from "@/components/decision/since-last-visit";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useIdentities } from "@/hooks/use-identity";
import { useExitWatch } from "@/hooks/use-intelligence";
import { useRadar } from "@/hooks/use-radar";
import { useScoresByMint, useTopScores } from "@/hooks/use-scores";
import {
  type TokenSnapshotMemory,
  diffToken,
  rememberVisit,
  rememberedTokens,
} from "@/lib/changes";
import { convictionOf } from "@/lib/conviction";
import { assessMarket } from "@/lib/market-quality";
import { type MissionState, missionStatus } from "@/lib/mission";
import { priorityRank, researchPriority } from "@/lib/research-priority";

/**
 * Mission Control — the daily briefing.
 *
 * Phase 13 turned this page from a set of category shelves into a briefing
 * with a work list. The order is deliberate and it is the whole argument:
 *
 *   1. **Mission Brief** — is today worth your time at all?
 *   2. **Opportunity Queue** — if it is, what do you look at first?
 *   3. **Since your last visit** — what moved while you were away?
 *   4. **Radar Scoreboard** — how has the platform actually done?
 *
 * The scoreboard sits last on purpose. It is the record LETZMOON is judged by,
 * and putting the judgement *after* the recommendations means a user reaches
 * the claims already knowing what the platform's calls have been worth.
 *
 * Everything derives from data already on the wire — the same queries the
 * previous version issued plus the batched clone lookup. No endpoint was added
 * or changed for Phase 13.
 */
export default function CommandPage() {
  const scores = useScoresByMint();
  const top = useTopScores(100);
  const radar = useRadar({ sort: "score", pageSize: 50 });
  const exit = useExitWatch();

  const scored = useMemo(() => top.data?.items ?? [], [top.data]);
  const radarEntries = useMemo(() => radar.data?.items ?? [], [radar.data]);

  // Read the visit baseline once per mount. Re-reading would diff against
  // memory this very render wrote, and report nothing forever.
  const [baseline] = useState(() => rememberedTokens());

  const exitSeverity = useMemo(() => {
    const map = new Map<string, "clear" | "watch" | "elevated">();
    for (const item of exit.data?.items ?? []) {
      map.set(item.mint_address, item.severity as "clear" | "watch" | "elevated");
    }
    return map;
  }, [exit.data]);

  const radarByMint = useMemo(
    () => new Map(radarEntries.map((entry) => [entry.mint_address, entry])),
    [radarEntries],
  );
  const tokenByMint = useMemo(
    () => new Map(scored.map((item) => [item.token.mint_address, item.token])),
    [scored],
  );

  // Everything the platform currently has an opinion about, from either source.
  const candidateMints = useMemo(
    () => [
      ...new Set([
        ...radarEntries.map((entry) => entry.mint_address),
        ...scored.map((item) => item.token.mint_address),
      ]),
    ],
    [radarEntries, scored],
  );

  const identities = useIdentities(candidateMints.slice(0, 100));

  /** Classify every candidate. Pure inputs, so this recomputes only on change. */
  const classified = useMemo(() => {
    return candidateMints.map((mint) => {
      const score = scores.byMint.get(mint);
      const entry = radarByMint.get(mint);
      const identity = identities.data?.get(mint);
      const severity = exitSeverity.get(mint) ?? null;

      const current: TokenSnapshotMemory = {
        score: score ? Number(score.score) : null,
        grade: score?.grade ?? null,
        liquidity: entry?.current_liquidity ? Number(entry.current_liquidity) : null,
        volume24h: null,
        currentMultiple: entry?.current_multiple ? Number(entry.current_multiple) : null,
        exitSeverity: severity,
      };
      const changes = diffToken(baseline[mint], current);

      const mission = missionStatus({
        currentMultiple: current.currentMultiple,
        peakMultiple: entry?.peak_multiple ? Number(entry.peak_multiple) : null,
        daysSinceDetection: entry?.days_since_detection
          ? Number(entry.days_since_detection)
          : 999,
        exitSeverity: severity,
        hasVeto: Boolean(score?.risk?.has_veto),
        // A Radar entry has by construction cleared the engine's minimum
        // observation count; a bare score row may not have.
        observations: score?.evidence?.observations ?? (entry ? 48 : 0),
      });

      const conviction = score ? convictionOf(score.grade, score.is_elite) : null;
      const confidence = score?.evidence?.confidence
        ? Number(score.evidence.confidence)
        : null;

      const priority = researchPriority({
        conviction,
        mission,
        confidence,
        changeCount: changes.length,
        hasVeto: Boolean(score?.risk?.has_veto),
        exitSeverity: severity,
        cloneRisk: identity?.clone_risk ?? null,
      });

      const token = tokenByMint.get(mint);
      return {
        mint,
        name: token?.name ?? entry?.name,
        symbol: token?.symbol ?? entry?.symbol,
        grade: score?.grade ?? null,
        isElite: score?.is_elite,
        score: score?.score ?? null,
        conviction,
        mission,
        priority,
        confidence,
        changes,
        identity,
      } satisfies QueueItem;
    });
  }, [
    candidateMints,
    scores.byMint,
    radarByMint,
    tokenByMint,
    identities.data,
    exitSeverity,
    baseline,
  ]);

  /**
   * The queue. Only Critical and High reach it.
   *
   * The attention economy made literal: Medium and Low stay searchable on the
   * Radar and the feed, but they do not get a slot in a briefing whose entire
   * value is that it is short.
   */
  const queue = useMemo(
    () =>
      [...classified]
        .filter(
          (item) =>
            item.priority.priority === "critical" || item.priority.priority === "high",
        )
        .sort(
          (a, b) =>
            priorityRank(a.priority.priority) - priorityRank(b.priority.priority) ||
            b.priority.score - a.priority.score,
        )
        .slice(0, 8),
    [classified],
  );

  const stateCounts = useMemo(() => {
    const counts: Partial<Record<MissionState, number>> = {};
    for (const item of classified) {
      counts[item.mission] = (counts[item.mission] ?? 0) + 1;
    }
    return counts;
  }, [classified]);

  const cloneWarnings = useMemo(
    () =>
      classified.filter(
        (item) =>
          item.identity?.clone_risk === "high" || item.identity?.clone_risk === "moderate",
      ).length,
    [classified],
  );

  const market = useMemo(() => {
    const confidences = classified
      .map((item) => item.confidence)
      .filter((value): value is number => value !== null)
      .sort((a, b) => a - b);

    return assessMarket({
      scored: scored.length,
      strongOrBetter: scored.filter(
        (item) => item.score?.grade === "high_conviction" || item.score?.grade === "strong",
      ).length,
      aboveEntry: radarEntries.filter(
        (entry) => Number(entry.current_multiple ?? 0) >= 1,
      ).length,
      tracked: radarEntries.length,
      deteriorating: [...exitSeverity.values()].filter((s) => s !== "clear").length,
      medianConfidence: confidences.length
        ? (confidences[Math.floor(confidences.length / 2)] ?? 0)
        : 0,
      cloneWarnings,
    });
  }, [classified, scored, radarEntries, exitSeverity, cloneWarnings]);

  const movers = useMemo(() => {
    const label = (item: (typeof classified)[number]) =>
      item.symbol ?? item.name ?? `${item.mint.slice(0, 4)}…${item.mint.slice(-4)}`;

    const gain = classified.find((item) =>
      item.changes.some((c) => c.code === "RETURN_MOVED" && c.direction === "up"),
    );
    const drop = classified.find((item) =>
      item.changes.some((c) => c.code === "RETURN_MOVED" && c.direction === "down"),
    );

    return {
      gain: gain ? { label: label(gain), detail: gain.priority.whyToday } : null,
      drop: drop ? { label: label(drop), detail: drop.priority.whyToday } : null,
    };
  }, [classified]);

  // Record what was shown, so the next visit has a baseline to diff against.
  useEffect(() => {
    if (classified.length === 0) return;
    const memory: Record<string, TokenSnapshotMemory> = {};
    for (const item of classified) {
      const entry = radarByMint.get(item.mint);
      memory[item.mint] = {
        score: item.score ? Number(item.score) : null,
        grade: item.grade ?? null,
        liquidity: entry?.current_liquidity ? Number(entry.current_liquidity) : null,
        volume24h: null,
        currentMultiple: entry?.current_multiple ? Number(entry.current_multiple) : null,
        exitSeverity: exitSeverity.get(item.mint) ?? null,
      };
    }
    rememberVisit(memory, new Date());
  }, [classified, radarByMint, exitSeverity]);

  const loading = top.isPending || radar.isPending;
  const unreachable = top.isError && radar.isError;

  if (loading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-64 rounded-panel" />
        <Skeleton className="h-40 rounded-panel" />
        <Skeleton className="h-40 rounded-panel" />
      </div>
    );
  }

  return (
    <div className="lm-enter flex flex-col gap-8">
      <DashboardPrimer />

      {unreachable ? (
        <Panel density="comfortable">
          <p className="text-sm text-ink-dim">
            The intelligence API could not be reached, so nothing below is
            current. This is a connection problem, not a quiet market.
          </p>
        </Panel>
      ) : null}

      <div className="relative">
        <MissionBrief
          analysed={top.data?.candidate_total ?? scored.length}
          market={market}
          worthInvestigating={queue.length}
          stateCounts={stateCounts}
          cloneWarnings={cloneWarnings}
          biggestGain={movers.gain}
          biggestDrop={movers.drop}
        />
        {/* Hidden below `lg`: on a phone this is decoration above the answer. */}
        <div className="pointer-events-none absolute right-6 top-4 hidden lg:block">
          <Mascot size={104} />
        </div>
      </div>

      <OpportunityQueue items={queue} />

      <SinceLastVisit
        scores={scores.byMint}
        radar={radarByMint}
        exitSeverity={exitSeverity}
      />

      {/* The record comes after the claims, so the claims are read in its light. */}
      <RadarScoreboard entries={radarEntries} isPending={radar.isPending} />
    </div>
  );
}
