"use client";

import Link from "next/link";

import { TokenActions } from "@/components/token/token-actions";
import { CATEGORY_LABEL, CATEGORY_TONE, formatMultiple, multipleTone } from "@/lib/radar";
import {
  baseRateSummary,
  changeTone,
  compactAge,
  compactUsd,
  evidenceBand,
  expiresIn,
  riskBand,
  signedPct,
  tokenNaming,
} from "@/lib/radar-row";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";

/**
 * ONE RADAR ROW
 *
 * Answers three questions without leaving the row: **should I care** (rank,
 * score, evidence), **why** (category, risk, the live signal's why-now), and
 * **what usually happened before** (the measured base rate for this category).
 *
 * Two rules govern everything here:
 *
 *  - **Nothing is estimated.** Every absent figure renders an explicit dash.
 *    A price we do not have is not a price of zero, and a risk we could not
 *    assess is not a risk of zero — on this model zero would read as maximum
 *    danger, which is the most consequential number to invent.
 *  - **No prose about a token is written here.** The signal's headline and
 *    why-now line arrive rendered from stable reason codes. A second opinion
 *    composed on the client can disagree with the engine that produced it.
 *
 * The base rate is measured history, never a forecast: "32% of 41 similar
 * signals reached 2×" is a property of the category, and the wording must never
 * drift into a claim about the token in front of the reader.
 */

/** A measured figure, or an explicit dash. Never a zero standing in for absent. */
function Cell({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string | null;
  tone?: "positive" | "negative" | "neutral";
  title?: string;
}) {
  return (
    <div title={title}>
      <p className="text-label uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          "mt-0.5 text-sm tabular-nums",
          value === null && "text-ink-faint",
          tone === "positive" && "text-safe",
          tone === "negative" && "text-danger",
          (!tone || tone === "neutral") && value !== null && "text-ink",
        )}
      >
        {value ?? "—"}
      </p>
    </div>
  );
}

function Chip({
  children,
  tone,
  title,
}: {
  children: React.ReactNode;
  tone: "safe" | "warn" | "danger" | "neutral";
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "rounded-chip border px-1.5 py-0.5 text-label uppercase tracking-wide",
        tone === "safe" && "border-safe/30 bg-safe/10 text-safe",
        tone === "warn" && "border-warn/30 bg-warn/10 text-warn",
        tone === "danger" && "border-danger/30 bg-danger/10 text-danger",
        tone === "neutral" && "border-line bg-elevated text-ink-dim",
      )}
    >
      {children}
    </span>
  );
}

export function RadarRow({ entry, rank }: { entry: RadarEntry; rank: number }) {
  const category = entry.category as keyof typeof CATEGORY_LABEL;
  const risk = riskBand(entry.risk_score);
  const evidence = evidenceBand(entry.evidence);
  const rate = baseRateSummary(entry.base_rate);
  const change = entry.market?.change_24h_pct ?? null;
  const { primary, secondary } = tokenNaming(entry);

  return (
    <article
      className="rounded-card border border-line bg-surface/40 p-4 transition-colors hover:border-line-bright"
      style={{ "--row-accent": CATEGORY_TONE[category] } as React.CSSProperties}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 w-6 shrink-0 text-right text-sm tabular-nums text-ink-faint">
            {rank}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/tokens/${entry.mint_address}`}
                className="truncate text-sm font-medium text-ink hover:underline"
              >
                {primary}
              </Link>
              {/* Suppressed when it repeats the symbol: "SAOF SAOF" is noise,
                  and a row that repeats itself reads as two facts. */}
              {secondary ? (
                <span className="truncate text-xs text-ink-faint">{secondary}</span>
              ) : null}
              <span
                className="rounded-chip px-1.5 py-0.5 text-label uppercase tracking-wide"
                style={{
                  color: CATEGORY_TONE[category],
                  background: `color-mix(in oklch, ${CATEGORY_TONE[category]} 12%, transparent)`,
                }}
              >
                {CATEGORY_LABEL[category] ?? entry.category}
              </span>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {risk ? (
                <Chip
                  tone={risk.tone}
                  title={
                    entry.risk_reasons.length > 0
                      ? entry.risk_reasons.join(" · ")
                      : undefined
                  }
                >
                  {risk.label}
                </Chip>
              ) : (
                <Chip tone="neutral" title="The last sweep had no source for risk.">
                  Risk not assessed
                </Chip>
              )}
              {evidence ? (
                <Chip
                  tone={evidence.tone}
                  title={`${entry.evidence}% of the model had data when this was scored.`}
                >
                  Evidence {evidence.label}
                </Chip>
              ) : null}
              {entry.liveness === "alive" ? null : (
                <Chip tone="neutral" title="Not observed in the last 24 hours.">
                  Liveness unknown
                </Chip>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-4">
          <div className="text-right">
            <p className="text-label uppercase tracking-wide text-ink-faint">
              Radar score
            </p>
            <p className="text-xl font-semibold tabular-nums text-ink">
              {Number(entry.opportunity_score).toFixed(0)}
            </p>
          </div>
          <TokenActions mint={entry.mint_address} />
        </div>
      </div>

      {/* The market strip. Absent entirely when the token has never been priced
          — a row of dashes is honest; a row of zeroes is not. */}
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
        <Cell label="Market cap" value={compactUsd(entry.market?.market_cap)} />
        <Cell label="Liquidity" value={compactUsd(entry.market?.liquidity_usd)} />
        <Cell label="Volume 24h" value={compactUsd(entry.market?.volume_24h)} />
        <Cell
          label="Change 24h"
          value={signedPct(change)}
          tone={changeTone(change)}
          title={
            change === null
              ? "No reading from a full 24 hours back. Not shown as 0%."
              : undefined
          }
        />
        <Cell
          label="Current"
          value={formatMultiple(entry.current_multiple)}
          tone={multipleTone(entry.current_multiple)}
        />
        <Cell
          label="Peak"
          value={formatMultiple(entry.peak_multiple)}
          tone={multipleTone(entry.peak_multiple)}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-faint">
        <span>Age {compactAge(entry.age_seconds) ?? "—"}</span>
        <span>Detected at {compactUsd(entry.first_market_cap) ?? "—"}</span>
        {entry.market?.dex_name ? <span>{entry.market.dex_name}</span> : null}
      </div>

      {/* Why now. Rendered by the backend; displayed verbatim. */}
      {entry.signal ? (
        <div className="mt-4 rounded-card border border-line bg-elevated/40 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-ink">
              {entry.signal.headline}
            </span>
            <Chip tone="neutral">
              expires in {expiresIn(entry.signal.expires_in_seconds) ?? "—"}
            </Chip>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-dim">
            {entry.signal.why_now}
          </p>
        </div>
      ) : null}

      {/* What usually happened before. Measured, never predicted. */}
      {rate ? (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
          <span className="text-ink-dim">{rate.headline}</span>
          {rate.quotable ? (
            <>
              {rate.lines.map((line) => (
                <span key={line} className="tabular-nums text-ink-faint">
                  {line}
                </span>
              ))}
              <span className="tabular-nums text-ink-faint">
                median peak {formatMultiple(entry.base_rate?.median_peak_multiple)}
              </span>
            </>
          ) : (
            <span className="text-ink-faint">{rate.lines[0]}</span>
          )}
        </div>
      ) : null}
    </article>
  );
}
