"use client";

import { useEffect, useMemo } from "react";

import { DashboardPrimer } from "@/components/alpha/dashboard-primer";
import { OpportunityCard } from "@/components/decision/opportunity-card";
import { RadarScoreboard } from "@/components/decision/radar-scoreboard";
import { SinceLastVisit } from "@/components/decision/since-last-visit";
import { Why } from "@/components/decision/why";
import { Mascot } from "@/components/brand/mascot";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useIdentities } from "@/hooks/use-identity";
import { useExitWatch } from "@/hooks/use-intelligence";
import { useRadar } from "@/hooks/use-radar";
import { useScoresByMint, useTopScores } from "@/hooks/use-scores";
import { type TokenSnapshotMemory, rememberVisit } from "@/lib/changes";
import { buildSections } from "@/lib/sections";

/**
 * Today's Opportunities — the home page.
 *
 * Phase 12 replaced the operator dashboard that used to live here. Discovery
 * totals, stream state, latency and division diagnostics all moved to
 * `/system`: they told a user the platform was working, which is not the same
 * as telling them anything worth acting on, and they occupied the top of the
 * page where the answer should be.
 *
 * What replaces them is a set of sections that each say what they measure
 * before showing a single number. The ordering is deliberate — conviction and
 * momentum first, deterioration and risk last — but every section renders on
 * every visit, including the unflattering ones. A page that shows only what is
 * going well is a pitch, not an instrument.
 */
export default function CommandPage() {
  const scores = useScoresByMint();
  const top = useTopScores(100);
  const radar = useRadar({ sort: "score", pageSize: 50 });
  const exit = useExitWatch();

  const scored = useMemo(() => top.data?.items ?? [], [top.data]);
  const radarEntries = useMemo(() => radar.data?.items ?? [], [radar.data]);

  const exitSeverity = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of exit.data?.items ?? []) {
      map.set(item.mint_address, item.severity);
    }
    return map;
  }, [exit.data]);

  const sections = useMemo(
    () => buildSections({ scored, radar: radarEntries, exitSeverity }),
    [scored, radarEntries, exitSeverity],
  );

  const radarByMint = useMemo(
    () => new Map(radarEntries.map((entry) => [entry.mint_address, entry])),
    [radarEntries],
  );
  const tokenByMint = useMemo(
    () => new Map(scored.map((item) => [item.token.mint_address, item.token])),
    [scored],
  );

  // One batched clone-risk request for every mint on the page rather than one
  // per card — the same deduplication discipline the scoring hooks follow.
  const visibleMints = useMemo(
    () => [...new Set(sections.flatMap((section) => section.mints))],
    [sections],
  );
  const identities = useIdentities(visibleMints);

  // Record what the user was shown, so the next visit has a baseline to diff
  // against. After render, and only once there is real data to remember.
  useEffect(() => {
    if (visibleMints.length === 0) return;

    const memory: Record<string, TokenSnapshotMemory> = {};
    for (const mint of visibleMints) {
      const score = scores.byMint.get(mint);
      const entry = radarByMint.get(mint);
      memory[mint] = {
        score: score ? Number(score.score) : null,
        grade: score?.grade ?? null,
        liquidity: entry?.current_liquidity ? Number(entry.current_liquidity) : null,
        volume24h: null,
        currentMultiple: entry?.current_multiple ? Number(entry.current_multiple) : null,
        exitSeverity: exitSeverity.get(mint) ?? null,
      };
    }
    rememberVisit(memory, new Date());
  }, [visibleMints, scores.byMint, radarByMint, exitSeverity]);

  const loading = top.isPending || radar.isPending;
  const unreachable = top.isError && radar.isError;

  return (
    <div className="flex flex-col gap-8">
      <DashboardPrimer />

      {/* --- Mission Control hero ---------------------------------------- */}
      <header className="relative flex items-center justify-between gap-6 overflow-hidden rounded-panel border border-line/60 bg-surface/40 px-6 py-7 backdrop-blur-xl">
        <div className="flex flex-col gap-2">
          <p className="text-xs uppercase tracking-[0.14em] text-brand-accent">
            Mission Control
          </p>
          <h1 className="text-balance text-3xl font-medium tracking-tight text-ink">
            What deserves your attention today
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
            Every section says what it measures and why these projects are in it.
            LETZMOON reports what it can observe. It does not predict returns,
            and nothing here is a recommendation.
          </p>
        </div>
        {/* Hidden below `sm`: on a phone this is 340px of decoration above the
            answer the user opened the app for. */}
        <Mascot size={132} className="hidden shrink-0 sm:block" />
      </header>

      {/* --- The record, before the pitch -------------------------------- */}
      <RadarScoreboard entries={radarEntries} isPending={radar.isPending} />

      <SinceLastVisit
        scores={scores.byMint}
        radar={radarByMint}
        exitSeverity={exitSeverity}
      />

      {unreachable ? (
        <Panel density="comfortable">
          <p className="text-sm text-ink-dim">
            The intelligence API could not be reached, so nothing below is
            current. This is a connection problem, not a quiet market.
          </p>
        </Panel>
      ) : null}

      {sections.map((section) => (
        <section key={section.definition.id} className="flex flex-col gap-3">
          <header className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-lg font-medium tracking-tight text-ink">
                {section.definition.title}
              </h2>
              <Why>{section.definition.basis}</Why>
            </div>
            <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
              {section.definition.description}
            </p>
          </header>

          {loading ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-32 rounded-panel" />
              ))}
            </div>
          ) : section.mints.length === 0 ? (
            <Panel density="compact">
              <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
                Nothing qualified for this section right now. That is a reading,
                not a gap — the conditions it describes are simply not present in
                what LETZMOON can currently observe.
              </p>
            </Panel>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {section.mints.map((mint) => {
                const entry = radarByMint.get(mint);
                const token = tokenByMint.get(mint);
                return (
                  <OpportunityCard
                    key={mint}
                    mint={mint}
                    name={token?.name ?? entry?.name}
                    symbol={token?.symbol ?? entry?.symbol}
                    score={scores.byMint.get(mint)}
                    radar={entry}
                    identity={identities.data?.get(mint)}
                  />
                );
              })}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
