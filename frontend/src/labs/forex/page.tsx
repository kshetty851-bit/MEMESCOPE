"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TabPanel, Tabs } from "@/components/ui/tabs";

import { CompareView } from "./compare";
import { dateError } from "./config";
import { Configure } from "./configure";
import { DataPanel } from "./data-panel";
import { Experiments } from "./experiments";
import { Section } from "./generic";
import { useCreateRun, useForexData, useForexMeta, useRun } from "./hooks";
import { ResearchView } from "./research";
import { BacktestView } from "./results";
import { ErrorLine, RunStatus } from "./run-status";
import type { RunDetail, RunKind, RunOut } from "./types";
import { useRunForm } from "./use-run-form";

type TabId = "data" | "configure" | "results" | "research" | "compare" | "experiments";

export const PAPER_BANNER =
  "Research and paper only — no broker connection, no live trading.";

/** Shows one run: its progress or failure while it works, then `children`. */
function RunTab({
  id,
  empty,
  children,
}: {
  id: number | null;
  empty: { title: string; body: string };
  children: (detail: RunDetail) => ReactNode;
}) {
  const run = useRun(id);
  if (id === null) return <EmptyState {...empty} />;
  if (run.isLoading) return <Skeleton className="h-72 w-full" />;
  if (run.isError || !run.data) {
    return (
      <ErrorState
        title="Could not load the run"
        body="The run endpoint did not answer."
        onRetry={() => void run.refetch()}
      />
    );
  }
  const { run: r, result } = run.data;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-ink-3" data-testid="run-meta">
        Run {r.id}
        {r.name ? ` · ${r.name}` : ""} · {r.status}
        {r.data_fingerprint ? ` · data ${r.data_fingerprint.slice(0, 10)}` : ""} · config v
        {r.config_version} · app {r.app_version}
      </p>
      <RunStatus run={r} />
      {r.status === "done" && result ? children(run.data) : null}
    </div>
  );
}

/**
 * FOREX STRATEGY LAB. Strategy research on stored candles: configure, backtest,
 * validate out of sample, stress the costs, compare. Every figure and sentence
 * is the API's; the page lays them out and computes nothing. There is no broker
 * here to connect to, and nothing on the page can place an order.
 */
export function ForexLabPage() {
  const [tab, setTab] = useState<TabId>("data");
  const [ids, setIds] = useState<
    Record<"backtest" | "research" | "compare", number | null>
  >({
    backtest: null,
    research: null,
    compare: null,
  });
  const meta = useForexMeta();
  const data = useForexData();
  const form = useRunForm(meta.data, data.data?.datasets);
  const compareRun = useCreateRun();

  function open(run: RunOut) {
    if (run.kind === "backtest" || run.kind === "research" || run.kind === "compare") {
      setIds((prev) => ({ ...prev, [run.kind]: run.id }));
      setTab(run.kind === "backtest" ? "results" : run.kind);
    } else {
      setTab("data");
    }
  }

  const priceDecimals = (symbol: string) =>
    meta.data?.instruments.find((i) => i.symbol === symbol)?.price_decimals ?? 5;

  const disclaimer = meta.data?.disclaimer ?? null;
  const compareDates = form.form
    ? dateError(form.form.start, form.form.end)
    : "Choose a start and end date.";

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Forex Strategy Lab</h1>
        <p className="max-w-[70ch] text-sm text-ink-dim">
          Backtests, out-of-sample validation and cost stress tests on stored candles.
          Results describe what a rule did in the past.
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
        aria-label="Forex Lab views"
        value={tab}
        onChange={setTab}
        panelId="forex-panel"
        items={[
          { value: "data", label: "Data" },
          { value: "configure", label: "Configure" },
          { value: "results", label: "Results" },
          { value: "research", label: "Research" },
          { value: "compare", label: "Compare" },
          { value: "experiments", label: "Experiments" },
        ]}
      />

      <TabPanel id="forex-panel" value={tab}>
        {tab === "data" ? <DataPanel meta={meta.data} /> : null}

        {tab === "configure" ? (
          meta.isLoading || (meta.data && !form.form) ? (
            <Skeleton className="h-72 w-full" />
          ) : meta.isError || !meta.data ? (
            <ErrorState
              title="Could not load the strategy settings"
              body="The meta endpoint did not answer."
              onRetry={() => void meta.refetch()}
            />
          ) : (
            <Configure
              meta={meta.data}
              form={form}
              onStarted={(run) => {
                setIds((prev) => ({
                  ...prev,
                  [run.kind === "research" ? "research" : "backtest"]: run.id,
                }));
                setTab(run.kind === "research" ? "research" : "results");
              }}
            />
          )
        ) : null}

        {tab === "results" ? (
          <RunTab
            id={ids.backtest}
            empty={{
              title: "No backtest open",
              body: "Run one from Configure, or open one from Experiments.",
            }}
          >
            {(detail) => (
              <BacktestView
                detail={detail}
                disclaimer={disclaimer}
                priceDecimals={
                  detail.result?.type === "backtest"
                    ? priceDecimals(detail.result.data.symbol)
                    : 5
                }
              />
            )}
          </RunTab>
        ) : null}

        {tab === "research" ? (
          <RunTab
            id={ids.research}
            empty={{
              title: "No research run open",
              body: "Run research from Configure, or open one from Experiments.",
            }}
          >
            {(detail) => <ResearchView detail={detail} disclaimer={disclaimer} />}
          </RunTab>
        ) : null}

        {tab === "compare" ? (
          <div className="flex flex-col gap-4">
            <Section
              title="Compare all strategies"
              hint="Runs every strategy with its default settings over the Configure date range and ranks the scorecards."
            >
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  variant="primary"
                  loading={compareRun.isPending}
                  disabled={!form.form || compareDates !== null}
                  onClick={() => {
                    if (!form.form) return;
                    compareRun.mutate(
                      {
                        kind: "compare",
                        start: `${form.form.start}T00:00:00Z`,
                        end: `${form.form.end}T23:59:59Z`,
                      },
                      {
                        onSuccess: (run) =>
                          setIds((prev) => ({ ...prev, compare: run.id })),
                      },
                    );
                  }}
                >
                  Compare all strategies
                </Button>
                {compareDates ? (
                  <span className="text-xs text-ink-3">{compareDates}</span>
                ) : null}
              </div>
              <div className="mt-3">
                <ErrorLine error={compareRun.error} action="run comparisons" />
              </div>
            </Section>
            <RunTab
              id={ids.compare}
              empty={{ title: "No comparison yet", body: "Start one above." }}
            >
              {(detail) => <CompareView detail={detail} />}
            </RunTab>
          </div>
        ) : null}

        {tab === "experiments" ? <Experiments onOpen={open} /> : null}
      </TabPanel>

      <p className="text-xs text-ink-dim">
        Research and paper only · candle times are UTC · past results do not forecast future
        ones
      </p>
    </div>
  );
}

export type { RunKind };
