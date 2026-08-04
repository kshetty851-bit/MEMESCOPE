"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Label } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { HistoryFeed } from "@/components/record/history-feed";
import { Journey } from "@/components/record/journey";
import { TokenActions } from "@/components/token/token-actions";
import { usePaperPositions } from "@/hooks/use-paper";
import { byMint, exitLabel, usd } from "@/lib/paper";
import { useRadar, useRadarBenchmark, useRadarPerformance } from "@/hooks/use-radar";
import { formatMultiple } from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { PaperPosition } from "@/types/paper";
import type { RadarEntry, RadarPerformance } from "@/types/radar";

/**
 * TRACK RECORD
 *
 * The permanent record of every Radar detection, including the ones that went
 * to zero. This page is the argument for trusting anything else in the product,
 * and it only works if it is complete.
 *
 * Three rules govern everything below, and each is enforced rather than
 * intended:
 *
 *  - **Nothing is hidden.** There is no filter that removes losers, and the
 *    default sort is newest-first, not best-first. Sorting by performance by
 *    default is a Hall of Fame wearing a track record's name.
 *  - **Peak and current are always shown together.** A call that reached 18x
 *    and fell to 0.30x is not an 18x call, and showing only the peak would say
 *    it was.
 *  - **Nothing is estimated.** Every figure is an aggregate over stored rows.
 *    Where no row supports a number it renders "—", never zero: "we have not
 *    measured this" and "this is zero" are different claims.
 */

/** Tier -> badge. Ordered ascending so the highest earned reads last. */
const TIER_BADGE: Record<string, string> = {
  "2x": "⭐",
  "5x": "⭐⭐",
  "10x": "⭐⭐⭐",
  "25x": "🏆",
  "50x": "🚀",
  "100x": "👑",
};

const TIER_ORDER = ["2x", "5x", "10x", "25x", "50x", "100x", "250x", "500x", "1000x"];

type ReachedFilter = "all" | "2x" | "5x" | "10x";
type SortKey = "newest" | "peak" | "current";

function n(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Money, compact. Returns null so callers can render "—" themselves. */
function money(value: string | null | undefined): string | null {
  const parsed = n(value);
  if (parsed === null) return null;
  if (parsed >= 1_000_000) return `$${(parsed / 1_000_000).toFixed(1)}M`;
  if (parsed >= 1_000) return `$${(parsed / 1_000).toFixed(0)}K`;
  return `$${parsed.toFixed(0)}`;
}

function pct(value: string | null | undefined): string | null {
  const parsed = n(value);
  return parsed === null ? null : `${(parsed * 100).toFixed(0)}%`;
}

function days(value: string | null | undefined): string | null {
  const parsed = n(value);
  return parsed === null ? null : `${parsed.toFixed(1)}d`;
}

/** A measured figure, or an explicit dash. Never a zero standing in for absent. */
function Stat({
  label,
  value,
  tone,
  note,
}: {
  label: string;
  value: string | null;
  tone?: "good" | "bad";
  note?: string;
}) {
  return (
    <div className="rounded-card border border-line bg-surface/40 px-4 py-3">
      <p className="text-label uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          value === null && "text-ink-faint",
          tone === "good" && "text-safe",
          tone === "bad" && "text-danger",
          !tone && value !== null && "text-ink",
        )}
      >
        {value ?? "—"}
      </p>
      {note ? <p className="mt-1 text-xs text-ink-faint">{note}</p> : null}
    </div>
  );
}

/** Horizontal distribution bar. Width is a share of the total detected. */
function DistributionRow({
  label,
  count,
  total,
}: {
  label: string;
  count: number;
  total: number;
}) {
  const share = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-xs tabular-nums text-ink-dim">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-elevated">
        <div
          className="h-full rounded-full bg-plasma/70"
          style={{ width: `${Math.max(share, count > 0 ? 1.5 : 0)}%` }}
        />
      </div>
      <span className="w-20 shrink-0 text-right text-xs tabular-nums text-ink-dim">
        {count} · {share.toFixed(0)}%
      </span>
    </div>
  );
}

function Badges({ tiers }: { tiers: string[] }) {
  if (tiers.length === 0) return <span className="text-ink-faint">—</span>;
  const ordered = [...tiers].sort(
    (a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b),
  );
  return (
    <span title={ordered.join(" · ")}>
      {ordered.map((tier) => TIER_BADGE[tier] ?? "").join("")}
    </span>
  );
}

/**
 * Was this token traded, and how did it go?
 *
 * Deliberately never offers an action. The strategy enters on its own published
 * rule with no manual step, so a token the wallet has not taken reads "—",
 * never "buy" — implying a button here would be the discretion the whole design
 * excludes.
 */
function PaperCell({ position }: { position: PaperPosition | undefined }) {
  if (!position) return <span className="text-ink-faint">—</span>;

  const pnl = usd(position.pnl_usd);
  const closed = position.status === "closed";
  const value = n(position.pnl_usd);

  return (
    <span
      className="whitespace-nowrap tabular-nums"
      title={
        closed
          ? `${exitLabel(position.exit_reason) ?? "Closed"} · entered at rank #${position.entry_rank}`
          : `Open · entered at rank #${position.entry_rank}`
      }
    >
      <span
        className={cn(
          value === null && "text-ink-faint",
          value !== null && value > 0 && "text-safe",
          value !== null && value < 0 && "text-danger",
          value === 0 && "text-ink-dim",
        )}
      >
        {pnl ?? "—"}
      </span>
      <span className="ml-1.5 text-xs text-ink-faint">
        {closed ? (exitLabel(position.exit_reason) ?? "closed") : "open"}
      </span>
    </span>
  );
}

function Reached({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? "text-safe" : "text-ink-faint"} aria-label={ok ? "yes" : "no"}>
      {ok ? "✓" : "·"}
    </span>
  );
}

export default function TrackRecordPage() {
  const performance = useRadarPerformance();
  const benchmark = useRadarBenchmark();
  // The whole record, not a page of it: this table's entire purpose is that
  // nothing is left out, and `include_inactive` is what keeps dead entries in.
  const record = useRadar({ pageSize: 100, includeInactive: true, sort: "detected" });
  // "Was this token traded?" answered from the wallet's own rows. One request
  // for the page, indexed by mint — the paper slice stays independent of the
  // Radar, and the Radar's hot path takes no extra query.
  const paper = usePaperPositions();

  const [reached, setReached] = useState<ReachedFilter>("all");
  const [sort, setSort] = useState<SortKey>("newest");

  const traded = useMemo(() => byMint(paper.data?.items ?? []), [paper.data]);

  const rows = useMemo(() => {
    const items: RadarEntry[] = record.data?.items ?? [];
    const threshold = reached === "all" ? 0 : Number(reached.replace("x", ""));
    const filtered =
      threshold === 0
        ? items
        : items.filter((item) => (n(item.peak_multiple) ?? 0) >= threshold);

    const sorted = [...filtered];
    if (sort === "peak") {
      sorted.sort((a, b) => (n(b.peak_multiple) ?? 0) - (n(a.peak_multiple) ?? 0));
    } else if (sort === "current") {
      sorted.sort((a, b) => (n(b.current_multiple) ?? 0) - (n(a.current_multiple) ?? 0));
    }
    return sorted;
  }, [record.data, reached, sort]);

  if (performance.isError || record.isError) {
    return (
      <div className="mx-auto max-w-6xl pb-8">
        <ErrorState
          body="The track record is not responding. The record itself is append-only and intact — this is a read failure."
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  const data: RadarPerformance | undefined = performance.data;
  const total = data?.total_opportunities ?? 0;
  const tierCount = (tier: string) =>
    data?.tiers.find((entry) => entry.tier === tier)?.count ?? 0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 pb-16">
      <header>
        <Label>Track record</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          Every Radar detection. Every outcome. Nothing hidden.
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-dim">
          Measured from the moment each project was detected — never from launch.
          Losses are counted in the same denominator as wins, and nothing is removed
          once recorded.
        </p>
      </header>

      {performance.isPending ? (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-20" />
          ))}
        </div>
      ) : total === 0 ? (
        <EmptyState
          agent="oracle"
          title="No detections recorded yet"
          body="The Radar has not detected anything yet. Once it does, every detection appears here permanently — including the ones that do not work out."
        />
      ) : (
        <>
          {/* Summary ------------------------------------------------------ */}
          <section className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <Stat label="Total detected" value={String(total)} />
            <Stat
              label="Reached 2×"
              value={`${tierCount("2x")} · ${((tierCount("2x") / total) * 100).toFixed(0)}%`}
              tone={tierCount("2x") > 0 ? "good" : undefined}
            />
            <Stat label="Reached 5×" value={String(tierCount("5x"))} />
            <Stat label="Reached 10×" value={String(tierCount("10x"))} />
            <Stat label="Reached 100×" value={String(tierCount("100x"))} />
            <Stat label="Still active" value={String(data?.active_opportunities ?? 0)} />
            <Stat
              label="Expired"
              value={String(data?.expired_opportunities ?? 0)}
              note="Nothing marks an entry inactive yet"
            />
            <Stat
              label="Median peak"
              value={formatMultiple(data?.median_peak_multiple)}
            />
            <Stat
              label="Best ever"
              value={formatMultiple(data?.best_peak_multiple)}
              tone="good"
            />
            <Stat label="Avg time to 2×" value={days(data?.average_days_to_2x)} />
            <Stat
              label="Avg drawdown"
              value={pct(data?.average_drawdown)}
              tone="bad"
              note="From peak"
            />
            <Stat
              label="Last updated"
              value={
                data?.observed_at
                  ? new Date(data.observed_at).toLocaleTimeString()
                  : null
              }
            />
          </section>

          {/* Distribution ------------------------------------------------- */}
          <section className="rounded-card border border-line bg-surface/40 p-5">
            <h2 className="text-sm font-semibold text-ink">Distribution</h2>
            <p className="mt-1 text-xs text-ink-faint">
              How far detections actually ran, as a share of everything detected.
            </p>
            <div className="mt-4 flex flex-col gap-2">
              <DistributionRow label="Detected" count={total} total={total} />
              {["2x", "5x", "10x", "25x", "50x", "100x"].map((tier) => (
                <DistributionRow
                  key={tier}
                  label={tier}
                  count={tierCount(tier)}
                  total={total}
                />
              ))}
            </div>
          </section>

          {/* Portfolio-style statistics ----------------------------------- */}
          <section>
            <h2 className="text-sm font-semibold text-ink">Performance</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <Stat label="Total calls" value={String(total)} />
              <Stat label="2× rate" value={pct(data?.success_rate)} />
              <Stat
                label="Median current"
                value={formatMultiple(data?.median_current_multiple)}
                tone="bad"
              />
              <Stat
                label="Average peak"
                value={formatMultiple(data?.average_peak_multiple)}
              />
              <Stat
                label="Worst call"
                value={formatMultiple(data?.worst_current_multiple)}
                tone="bad"
              />
              <Stat label="Avg days tracked" value={days(data?.average_days_tracked)} />
              <Stat
                label="Avg detection mcap"
                value={money(data?.average_detection_market_cap)}
              />
              <Stat
                label="Largest peak mcap"
                value={money(data?.largest_peak_market_cap)}
              />
            </div>
          </section>

          {/* The record ---------------------------------------------------- */}
          <section>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-ink">
                Every detection{" "}
                <span className="font-normal text-ink-faint">({rows.length})</span>
              </h2>
              <div className="flex flex-wrap items-center gap-4 text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="text-ink-faint">Reached</span>
                  {(["all", "2x", "5x", "10x"] as ReachedFilter[]).map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setReached(option)}
                      className={cn(
                        "rounded px-2 py-1 transition-colors",
                        reached === option
                          ? "bg-plasma/15 text-plasma"
                          : "text-ink-faint hover:text-ink",
                      )}
                    >
                      {option === "all" ? "All" : option}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-ink-faint">Sort</span>
                  {(
                    [
                      ["newest", "Newest"],
                      ["peak", "Peak"],
                      ["current", "Current"],
                    ] as [SortKey, string][]
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setSort(key)}
                      className={cn(
                        "rounded px-2 py-1 transition-colors",
                        sort === key
                          ? "bg-plasma/15 text-plasma"
                          : "text-ink-faint hover:text-ink",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {record.isPending ? (
              <div className="mt-3 flex flex-col gap-2">
                {Array.from({ length: 8 }, (_, index) => (
                  <Skeleton key={index} className="h-12" />
                ))}
              </div>
            ) : (
              <div className="mt-3 overflow-x-auto rounded-card border border-line">
                <table className="w-full min-w-[1320px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
                      <th className="px-3 py-2 text-left font-normal">#</th>
                      <th className="px-3 py-2 text-left font-normal">Token</th>
                      <th className="px-3 py-2 text-right font-normal">Detected</th>
                      <th className="px-3 py-2 text-right font-normal">Now</th>
                      <th className="px-3 py-2 text-right font-normal">Peak</th>
                      <th className="px-3 py-2 text-right font-normal">Current ×</th>
                      <th className="px-3 py-2 text-right font-normal">Peak ×</th>
                      <th className="px-3 py-2 text-center font-normal">2×</th>
                      <th className="px-3 py-2 text-center font-normal">5×</th>
                      <th className="px-3 py-2 text-center font-normal">10×</th>
                      <th className="px-3 py-2 text-center font-normal">100×</th>
                      <th className="px-3 py-2 text-right font-normal">Age</th>
                      <th className="px-3 py-2 text-left font-normal">Journey</th>
                      <th className="px-3 py-2 text-center font-normal">Badges</th>
                      <th className="px-3 py-2 text-left font-normal">Status</th>
                      <th className="px-3 py-2 text-right font-normal">Paper trade</th>
                      <th className="px-3 py-2 text-right font-normal">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((entry, index) => {
                      const peak = n(entry.peak_multiple) ?? 0;
                      return (
                        <tr
                          key={entry.mint_address}
                          className="border-b border-line/60 last:border-0 hover:bg-elevated/40"
                        >
                          <td className="px-3 py-2 tabular-nums text-ink-faint">
                            {index + 1}
                          </td>
                          <td className="px-3 py-2">
                            <Link
                              href={`/tokens/${entry.mint_address}`}
                              className="text-ink hover:text-plasma"
                            >
                              {entry.symbol ?? entry.mint_address.slice(0, 6)}
                              {entry.name ? (
                                <span className="ml-2 text-ink-faint">{entry.name}</span>
                              ) : null}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                            {money(entry.first_market_cap) ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                            {money(entry.current_market_cap) ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                            {money(entry.peak_market_cap) ?? "—"}
                          </td>
                          {/* Peak and current always side by side — never one
                              standing in for the other. */}
                          <td
                            className={cn(
                              "px-3 py-2 text-right tabular-nums",
                              (n(entry.current_multiple) ?? 0) >= 1
                                ? "text-safe"
                                : "text-danger",
                            )}
                          >
                            {formatMultiple(entry.current_multiple)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink">
                            {formatMultiple(entry.peak_multiple)}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Reached ok={peak >= 2} />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Reached ok={peak >= 5} />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Reached ok={peak >= 10} />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Reached ok={peak >= 100} />
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-faint">
                            {days(entry.days_since_detection) ?? "—"}
                          </td>
                          <td className="px-3 py-2">
                            <Journey
                              tiers={entry.achieved_tiers ?? []}
                              peakMultiple={entry.peak_multiple}
                              currentMultiple={entry.current_multiple}
                            />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Badges tiers={entry.achieved_tiers ?? []} />
                          </td>
                          <td
                            className={cn(
                              "px-3 py-2",
                              entry.liveness === "alive" ? "text-ink-dim" : "text-ink-faint",
                            )}
                            title={
                              entry.liveness === "alive"
                                ? "A market was observed in the last 24 hours"
                                : "No market observed recently — this is not a claim that it died"
                            }
                          >
                            {entry.liveness === "alive" ? "Alive" : "Unknown"}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <PaperCell position={traded.get(entry.mint_address)} />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <TokenActions mint={entry.mint_address} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <p className="mt-3 text-xs text-ink-faint">
              Peak and current are always shown together. A call that reached 18× and
              gave it back is not an 18× call.
            </p>
          </section>

          {/* Benchmark ----------------------------------------------------- */}
          <section className="rounded-card border border-line bg-surface/40 p-5">
            <h2 className="text-sm font-semibold text-ink">Benchmark</h2>
            <p className="mt-1 text-xs text-ink-faint">
              What buying every detection in equal size would have returned. Measured
              from the record, not simulated.
            </p>
            {benchmark.data ? (
              <>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat
                    label="Buy every detection"
                    value={formatMultiple(benchmark.data.average_current_multiple)}
                    tone={
                      Number(benchmark.data.average_current_multiple ?? 0) >= 1
                        ? "good"
                        : "bad"
                    }
                    note="Mean current multiple"
                  />
                  <Stat
                    label="Median outcome"
                    value={formatMultiple(benchmark.data.median_current_multiple)}
                    tone="bad"
                    note="The typical call"
                  />
                  <Stat
                    label="Above entry"
                    value={`${benchmark.data.above_entry} of ${benchmark.data.entries}`}
                  />
                  <Stat
                    label="Below entry"
                    value={`${benchmark.data.below_entry} of ${benchmark.data.entries}`}
                    tone="bad"
                  />
                </div>
                <div className="mt-4 flex flex-col gap-1 text-xs text-ink-faint">
                  <p>Hold SOL — {benchmark.data.sol_note}</p>
                  <p>Paper wallet — {benchmark.data.paper_wallet_note}</p>
                </div>
              </>
            ) : (
              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                {Array.from({ length: 4 }, (_, index) => (
                  <Skeleton key={index} className="h-20" />
                ))}
              </div>
            )}
          </section>

          {/* Hall of history ------------------------------------------------ */}
          <section>
            <h2 className="text-sm font-semibold text-ink">History</h2>
            <p className="mt-1 text-xs text-ink-faint">
              Every detection and every milestone, newest first. Each line is a stored
              row — nothing is written for this feed.
            </p>
            <div className="mt-3 rounded-card border border-line px-4">
              <HistoryFeed />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
