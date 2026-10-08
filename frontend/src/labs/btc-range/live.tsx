"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";

import { EquityCurve, RangeChart } from "./charts";
import { when } from "./format";
import { Hero, ReasonsList } from "./hero";
import { MetricsStats, OpenPositionCard, SideTable, TradesTable } from "./metrics";
import type { StatusOut } from "./types";

function Notice({
  tone,
  title,
  children,
}: {
  tone: "warn" | "neutral";
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="status"
      className={
        tone === "warn"
          ? "rounded-md border border-warn/40 bg-warn/10 p-3"
          : "rounded-md border border-line bg-surface p-3"
      }
    >
      <p
        className={
          tone === "warn" ? "text-sm font-medium text-warn" : "text-sm font-medium text-ink"
        }
      >
        {title}
      </p>
      <p className="mt-0.5 max-w-[75ch] text-xs text-ink-2">{children}</p>
    </div>
  );
}

/**
 * Tab 1. `running: false` is a different statement from "running, found
 * nothing": the lab is off, nothing is being recorded, and the server's own
 * `reason` says why.
 */
export function LiveTab({
  status,
  entryZone,
}: {
  status: StatusOut;
  entryZone?: string | null;
}) {
  if (!status.running) {
    return (
      <EmptyState
        title="The BTC Range Lab is not running"
        body={
          status.reason ??
          "The server gave no reason. No candles are being read and no paper book is updating."
        }
      />
    );
  }

  const { signal, book, data } = status;

  return (
    <div className="flex flex-col gap-4">
      {data.stale ? (
        <Notice tone="warn" title="Stale data">
          The newest closed candle ({when(data.last_closed_at)}) is more than two candle
          periods old. The figures below describe that moment, not now.
        </Notice>
      ) : null}

      {status.reason ? (
        <Notice tone="neutral" title="Note from the server">
          {status.reason}
        </Notice>
      ) : null}

      <Hero price={status.price} signal={signal} book={book} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <Panel density="compact">
          <PanelHeader className="mb-3">
            <PanelTitle>
              Range · {status.symbol} {status.timeframe}
            </PanelTitle>
          </PanelHeader>
          <RangeChart candles={status.candles} signal={signal} entryZone={entryZone} />
        </Panel>
        <ReasonsList signal={signal} />
      </div>

      {book ? (
        <>
          <Panel density="compact">
            <PanelHeader className="mb-3">
              <PanelTitle>Paper book</PanelTitle>
              <span className="text-xs text-ink-3">
                since {when(book.started_at)} · config v{book.config_version}
              </span>
            </PanelHeader>
            <MetricsStats metrics={book.metrics} />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel density="compact">
              <PanelHeader className="mb-3">
                <PanelTitle>LONG vs SHORT</PanelTitle>
              </PanelHeader>
              <SideTable long={book.long} short={book.short} />
            </Panel>
            <Panel density="compact">
              <PanelHeader className="mb-3">
                <PanelTitle>Equity</PanelTitle>
              </PanelHeader>
              <EquityCurve points={book.equity_curve} />
            </Panel>
          </div>

          <OpenPositionCard position={book.open_position} />

          <Panel density="compact">
            <PanelHeader className="mb-3">
              <PanelTitle>Trade history</PanelTitle>
              <span className="text-xs text-ink-3">newest first · Dubai time</span>
            </PanelHeader>
            <TradesTable trades={book.trades} caption="Closed paper trades, newest first" />
          </Panel>
        </>
      ) : (
        <Panel density="compact">
          <p className="text-sm text-ink-3" data-testid="no-book">
            There is no paper book yet, so there is no P&amp;L to show.
          </p>
        </Panel>
      )}
    </div>
  );
}
