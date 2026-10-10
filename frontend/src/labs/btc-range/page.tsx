"use client";

import { useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { TabPanel, Tabs } from "@/components/ui/tabs";

import { useBtcMonthly, useBtcRangeConfig, useBtcRangeStatus } from "./hooks";
import { LiveTab } from "./live";
import { MonthlyTab } from "./monthly";
import { StrategyLab } from "./strategy-lab";

type TabId = "monthly" | "live" | "lab";

export const PAPER_BANNER = "Paper trading only — no wallet, no live orders.";

/**
 * BTC RANGE LAB. A paper-only strategy on BTC/USDT: it finds a trading range,
 * reports what it observes, and a paper book records what its calls would have
 * made. LONG / SHORT / WAIT are the strategy's calls, not advice. Every figure
 * and every sentence is the API's; the page only lays them out.
 */
export function BtcRangeLabPage() {
  const [tab, setTab] = useState<TabId>("monthly");
  const [labOpened, setLabOpened] = useState(false);
  const status = useBtcRangeStatus();
  const config = useBtcRangeConfig();
  const monthly = useBtcMonthly();

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">BTC Lab</h1>
        <p className="max-w-[65ch] text-sm text-ink-dim">
          Paper books on BTC/USDT. The monthly book goes long or short for a whole month at
          3×, following last month&apos;s direction. The range strategy is stopped.
        </p>
      </header>

      <div
        role="note"
        data-testid="paper-banner"
        className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm font-medium text-warn"
      >
        {PAPER_BANNER}
      </div>

      <Tabs
        aria-label="BTC Range Lab views"
        value={tab}
        onChange={(next) => {
          setTab(next);
          if (next === "lab") setLabOpened(true);
        }}
        panelId="btc-range-panel"
        items={[
          { value: "monthly", label: "Monthly 3× (paper)" },
          { value: "live", label: "Range (stopped)" },
          { value: "lab", label: "Strategy Lab" },
        ]}
      />

      <TabPanel id="btc-range-panel" value={tab}>
        {tab === "monthly" ? (
          monthly.isLoading ? (
            <Skeleton className="h-72 w-full" />
          ) : monthly.isError || !monthly.data ? (
            <ErrorState
              title="Could not load the monthly book"
              body="The monthly endpoint did not answer."
              onRetry={() => void monthly.refetch()}
            />
          ) : (
            <MonthlyTab data={monthly.data} />
          )
        ) : null}
        {tab === "live" ? (
          status.isLoading ? (
            <div className="flex flex-col gap-4" data-testid="live-loading">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-72 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : status.isError || !status.data ? (
            <ErrorState
              title="Could not load the BTC Range Lab"
              body="The status endpoint did not answer."
              onRetry={() => void status.refetch()}
            />
          ) : (
            <LiveTab
              status={status.data}
              entryZone={status.data.book?.config.entry_zone ?? null}
            />
          )
        ) : null}

        {/* Kept mounted once opened, only hidden: leaving for the Live tab must
            not throw away a half-edited form or the last backtest. */}
        {labOpened ? (
          <div hidden={tab !== "lab"}>
            {config.isLoading ? (
              <div className="flex flex-col gap-4" data-testid="lab-loading">
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-40 w-full" />
              </div>
            ) : config.isError || !config.data ? (
              <ErrorState
                title="Could not load the strategy settings"
                body="The config endpoint did not answer."
                onRetry={() => void config.refetch()}
              />
            ) : (
              <StrategyLab config={config.data} />
            )}
          </div>
        ) : null}
      </TabPanel>

      {tab === "live" && status.data?.running ? (
        <p className="text-xs text-ink-dim">
          Paper only · this page refreshes every 30s · times in Dubai time
        </p>
      ) : null}
    </div>
  );
}
