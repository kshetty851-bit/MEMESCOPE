"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { shortenAddress } from "@/lib/format";

import { CLOSE_REASON_LABELS } from "./api";
import { BreakoutChart } from "./chart";
import { compactUsd, plainPct, price, rate, STATE_CLASS, STATE_LABEL } from "./format";
import { useSetupDetail } from "./hooks";
import type { Position, Trade } from "./types";

/** Mirrors `config.PRE_ZONE_PCT`. Only used to shade the band on the chart. */
const PRE_ZONE_PCT = 6;

const COMPONENT_LABELS: Record<string, string> = {
  volume: "Volume",
  structure: "Rising lows",
  position: "Range position",
  compression: "Compression",
  hourly: "Hourly confirm",
};

function Bar({ label, value }: { label: string; value: number | null }) {
  const missing = value === null;
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-label uppercase text-ink-4">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-surface-2">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.round((value ?? 0) * 100)}%` }}
        />
      </div>
      <span className="w-12 text-right font-mono text-xs tabular-nums text-ink-2">
        {missing ? "n/a" : rate(value)}
      </span>
    </div>
  );
}

/**
 * The token panel: the chart the whole tab exists to get you to.
 *
 * Everything drawn here is served by `GET /labs/breakout/setups/{mint}` in one
 * response — the candles, the levels, the snapshot and the episode — so the
 * chart can never show a resistance from one moment and a price from another.
 */
export function TokenPanel({
  mint,
  onClose,
  position,
  trades,
}: {
  mint: string;
  onClose: () => void;
  position?: Position | null;
  trades: Trade[];
}) {
  const [timeframe, setTimeframe] = useState<"day" | "hour">("day");
  const { data, isLoading, isError } = useSetupDetail(mint);

  const bars = data?.candles?.[timeframe] ?? [];
  const snapshot = data?.latest_snapshot ?? null;
  const components = snapshot?.components ?? null;

  return (
    <Panel density="comfortable" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-sm text-ink">
              {data?.token?.symbol ?? shortenAddress(mint)}
            </h2>
            {snapshot && (
              <span
                className={`rounded border px-1.5 py-0.5 text-label uppercase ${
                  STATE_CLASS[snapshot.state] ?? STATE_CLASS.NONE
                }`}
              >
                {STATE_LABEL[snapshot.state] ?? snapshot.state}
              </span>
            )}
          </div>
          <p className="font-mono text-label text-ink-4">{shortenAddress(mint)}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded border border-line" role="group"
            aria-label="Candle timeframe">
            {(["day", "hour"] as const).map((frame) => (
              <button
                key={frame}
                type="button"
                onClick={() => setTimeframe(frame)}
                aria-pressed={timeframe === frame}
                className={`px-2 py-1 text-label uppercase ${
                  timeframe === frame ? "bg-surface-2 text-ink" : "text-ink-4"
                }`}
              >
                {frame === "day" ? "1D" : "1H"}
              </button>
            ))}
          </div>
          <button type="button" onClick={onClose}
            className="rounded border border-line px-2 py-1 text-label uppercase text-ink-3">
            Close
          </button>
        </div>
      </div>

      {isLoading && <Skeleton className="h-[300px] w-full" />}
      {isError && (
        <p className="text-sm text-down">Could not load this token.</p>
      )}

      {data && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_240px]">
          <BreakoutChart
            bars={bars}
            clusters={data.levels?.clusters ?? []}
            nearestResistance={data.levels?.nearest_resistance ?? null}
            preZonePct={PRE_ZONE_PCT}
            position={position ?? null}
            trades={trades}
            timeframe={timeframe}
          />

          <div className="space-y-4">
            <div>
              <p className="mb-2 text-label uppercase text-ink-4">Score components</p>
              {components ? (
                <div className="space-y-1.5">
                  {Object.entries(COMPONENT_LABELS).map(([key, label]) => (
                    <Bar
                      key={key}
                      label={label}
                      value={components[key as keyof typeof components] ?? null}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-ink-4">No snapshot yet.</p>
              )}
            </div>

            <dl className="space-y-1 text-xs">
              {[
                ["Score", snapshot ? String(snapshot.score) : "—"],
                ["Price", price(snapshot?.price ?? null)],
                ["Resistance", price(data.levels?.nearest_resistance ?? null)],
                ["Distance", plainPct(snapshot?.distance_pct ?? null, 2)],
                ["ATR (1d)", price(data.levels?.atr ?? null)],
                ["Liquidity", compactUsd(data.token?.liquidity_usd ?? null)],
                ["24h volume", compactUsd(data.token?.volume_24h_usd ?? null)],
                ["DEX", data.token?.dex ?? "—"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt className="text-ink-4">{label}</dt>
                  <dd className="font-mono tabular-nums text-ink-2">{value}</dd>
                </div>
              ))}
            </dl>

            {data.episode && (
              <div className="rounded border border-line p-2 text-xs">
                <p className="text-label uppercase text-ink-4">Episode</p>
                <p className="text-ink-2">
                  {data.episode.closed_at
                    ? (CLOSE_REASON_LABELS[data.episode.close_reason ?? ""] ??
                       data.episode.close_reason)
                    : "Open"}
                </p>
                {data.episode.trail25_result_pct !== null && (
                  <p className="font-mono text-ink-3">
                    trail25 {plainPct(data.episode.trail25_result_pct)}
                    {data.episode.outcome_gappy ? " (gappy)" : ""}
                  </p>
                )}
              </div>
            )}

            {snapshot?.hourly_missing && (
              <p className="text-xs text-warn">
                No hourly bars — score computed without confirmation and capped.
              </p>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
