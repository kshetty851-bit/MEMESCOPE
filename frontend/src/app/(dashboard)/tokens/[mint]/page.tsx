"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { InvestmentThesis } from "@/components/decision/investment-thesis";
import { OpportunityTimeline } from "@/components/decision/opportunity-timeline";
import { ProjectHealth } from "@/components/decision/project-health";
import { HistoryPanel } from "@/components/token/history-panel";
import { MarketPanel } from "@/components/token/market-panel";
import { RiskRead } from "@/components/token/risk-read";
import { ScoreWaterfall } from "@/components/token/score-waterfall";
import { TokenHeader } from "@/components/token/token-header";
import { VerdictBand } from "@/components/token/verdict-band";
import { WhyNowPanel } from "@/components/token/why-now-panel";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useIdentity } from "@/hooks/use-identity";
import { useLiveUpdates } from "@/hooks/use-live-updates";
import { useRadarEntry } from "@/hooks/use-radar";
import { usePaperPositions } from "@/hooks/use-paper";
import { byMint } from "@/lib/paper";
import { useTokenScore } from "@/hooks/use-scores";
import { ApiError, api } from "@/lib/api-client";
import { buildHealth } from "@/lib/health";
import { buildThesis } from "@/lib/thesis";
import { shortenAddress } from "@/lib/format";
import type { DiscoveredToken, TokenMarket } from "@/types/api";

/**
 * THE TOKEN INTELLIGENCE DOSSIER.
 *
 * What this replaces: a two-column grid of seven independent `Panel` cards —
 * market table on the left, and a right rail stacking thesis, health, timeline,
 * a narrated risk read and a seven-character "mission report" with no hierarchy
 * between them. The score the entire product is built on did not appear at the
 * top of the page at all; it was a line inside the fifth panel down.
 *
 * The rebuild is a *file*, read top to bottom:
 *
 *   1. Who is this          — sticky header, identity never scrolls away
 *   2. What is the verdict  — score, grade, risk, price, size, peak/current
 *   3. Why now              — the backend's sentence, signal, base rate
 *   4. The working          — tabs: how the score was built, market, history
 *
 * Everything below the verdict band exists to explain the verdict band.
 *
 * CACHE REUSE. The market and history queries use the same keys the scanner's
 * quick-detail panel uses, so arriving here from the scanner renders from cache
 * rather than refetching. The live-update invalidations already target them.
 */

type TabId = "analysis" | "market" | "history";

const TABS: { value: TabId; label: string }[] = [
  { value: "analysis", label: "Analysis" },
  { value: "market", label: "Market" },
  { value: "history", label: "History" },
];

export default function TokenIntelligencePage() {
  const params = useParams<{ mint: string }>();
  const mint = params.mint;
  const [tab, setTab] = useState<TabId>("analysis");
  const { status: liveStatus } = useLiveUpdates();

  const token = useQuery({
    queryKey: ["tokens", mint],
    queryFn: () => api.get<DiscoveredToken>(`/tokens/${mint}`),
  });

  const market = useQuery({
    queryKey: ["tokens", mint, "market"],
    queryFn: () => api.get<TokenMarket>(`/tokens/${mint}/market`),
    refetchInterval: liveStatus === "live" ? false : 30_000,
  });

  const scoreQuery = useTokenScore(mint);
  const radarEntry = useRadarEntry(mint);
  const identity = useIdentity(mint);
  // The trade, if the wallet took one. Needed here only so the timeline can put
  // entry and exit on the same clock as detection.
  const paper = usePaperPositions();

  if (token.error instanceof ApiError && token.error.status === 404) {
    return (
      <EmptyState
        title="Not in the archive"
        body={`${shortenAddress(mint, 8, 8)} has not been discovered by MEMESCOPE. If it launched moments ago, discovery may still be resolving it.`}
        action={
          <Link
            href="/command"
            className="rounded-md border border-line-control px-3 py-1.5 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
          >
            Back to the scanner
          </Link>
        }
      />
    );
  }

  if (token.error) {
    return (
      <ErrorState
        body="The intelligence archive did not respond. Records already stored are safe — this is a read failure."
        onRetry={() => void token.refetch()}
      />
    );
  }

  const snapshot = market.data?.market ?? null;
  // Only a `scored` envelope carries a body. Any other status is a real backend
  // state with its own sentence, never an error.
  const score = scoreQuery.data?.status === "scored" ? scoreQuery.data.score : null;
  const radar = radarEntry.data;
  const position = byMint(paper.data?.items ?? []).get(mint);

  return (
    <div className="flex flex-col gap-5 pb-8">
      <TokenHeader
        mint={mint}
        token={token.data}
        identity={identity.data}
        isPending={token.isPending}
      />

      <VerdictBand
        score={score}
        scoreStatus={scoreQuery.data?.status}
        isScorePending={scoreQuery.isPending}
        radar={radar}
        snapshot={snapshot}
        capturedAt={snapshot?.captured_at ?? radar?.market?.captured_at ?? null}
      />

      <Panel density="comfortable">
        <WhyNowPanel radar={radar} />
      </Panel>

      <div className="flex flex-col gap-3">
        <Tabs
          items={TABS}
          value={tab}
          onChange={setTab}
          panelId="token-detail-panel"
          aria-label="Token intelligence sections"
        />

        <TabPanel id="token-detail-panel" value={tab}>
          {tab === "analysis" ? (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
              <div className="flex min-w-0 flex-col gap-5">
                <Panel density="comfortable">
                  <ScoreWaterfall score={score} isPending={scoreQuery.isPending} />
                </Panel>
                <Panel density="comfortable">
                  <RiskRead
                    score={score}
                    status={scoreQuery.data?.status}
                    radar={radar}
                    isPending={scoreQuery.isPending}
                  />
                </Panel>
              </div>

              <aside className="flex min-w-0 flex-col gap-5">
                {scoreQuery.isPending ? (
                  <Panel density="comfortable">
                    <Skeleton className="h-40 w-full" />
                  </Panel>
                ) : (
                  <>
                    <InvestmentThesis
                      thesis={buildThesis(
                        score ?? null,
                        radar?.reasons?.map((reason) => reason.message),
                      )}
                    />
                    <ProjectHealth dimensions={buildHealth(score ?? null)} />
                  </>
                )}
                {radar ? (
                  <OpportunityTimeline entry={radar} position={position} />
                ) : null}
              </aside>
            </div>
          ) : tab === "market" ? (
            <Panel density="comfortable">
              {market.isPending ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <MarketPanel market={market.data} token={token.data} />
              )}
            </Panel>
          ) : (
            <Panel density="comfortable">
              <HistoryPanel mint={mint} />
            </Panel>
          )}
        </TabPanel>
      </div>
    </div>
  );
}
