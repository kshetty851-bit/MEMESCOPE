"use client";

import Link from "next/link";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { formatMultiple, multipleTone } from "@/lib/radar";
import {
  baseRateSummary,
  changeTone,
  compactAge,
  compactUsd,
  evidenceDots,
  expiresIn,
  riskLabel,
  signedPct,
  tokenNaming,
} from "@/lib/radar-row";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";

/**
 * ONE RADAR ROW
 *
 * Read top to bottom, it answers a trader's four questions in the order they
 * are asked: **why is this ranked here** (score, evidence, risk), **why now**
 * (one sentence), **is it worth watching** (the market strip), **has this kind
 * of token worked before** (the base rate).
 *
 * Three rules govern everything here, and each is asserted in the tests:
 *
 *  - **Nothing is estimated.** Every absent figure renders an explicit dash. A
 *    price we do not have is not a price of zero, and a risk we could not
 *    assess is not a risk of zero — on this model zero would read as maximum
 *    danger, the most consequential number to invent.
 *  - **No engine vocabulary reaches the screen.** `fresh_graduation`,
 *    `severity`, `provider_id`, `strength` and the engine's own `confidence`
 *    are accurate and internal. The backend hands this component the trader's
 *    wording; the component never derives its own.
 *  - **No prose about a token is composed here.** The signal label and the
 *    why-now sentence arrive rendered from stable codes. A second opinion
 *    written client-side can disagree with the engine that produced it.
 *
 * The base rate is measured history, never a forecast: "28% of 36 similar
 * signals reached 2×" is a property of the category, and no wording here may
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

/**
 * Evidence as four dots.
 *
 * A percentage beside a score invites the reader to multiply them. Dots say
 * "how much of the model had data" without pretending to be a second score.
 */
function EvidenceDots({ evidence }: { evidence: string | null }) {
  const filled = evidenceDots(evidence);
  const title =
    filled === null
      ? "Not scored yet, so no evidence is recorded."
      : `Evidence: ${Math.round(Number(evidence))}% of the model had data when this was scored.`;

  return (
    <span
      className="flex items-center gap-0.5"
      title={title}
      aria-label={
        filled === null ? "Evidence not recorded" : `Evidence ${filled} of 4`
      }
    >
      {[0, 1, 2, 3].map((index) => (
        <span
          key={index}
          aria-hidden
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            filled !== null && index < filled ? "bg-ink-dim" : "bg-line",
          )}
        />
      ))}
    </span>
  );
}

/** One-click paths out of the row. Every destination is distinct. */
function RowActions({ mint }: { mint: string }) {
  const link =
    "rounded px-1.5 py-1 text-xs text-ink-faint transition-colors hover:bg-elevated hover:text-ink";

  async function copy(event: React.MouseEvent) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(mint);
    } catch {
      // Clipboard can be blocked by permissions. Say nothing rather than
      // claim a copy that did not happen.
    }
  }

  return (
    <div className="flex items-center gap-0.5">
      <button type="button" onClick={copy} title="Copy mint address" className={link}>
        Copy
      </button>
      {/* Three distinct destinations. Before this, "Chart" and "DexScreener"
          were the same URL wearing two icons. */}
      <a
        href={`https://pump.fun/coin/${mint}`}
        target="_blank"
        rel="noopener noreferrer"
        title="Open the Pump.fun chart"
        className={link}
      >
        Chart
      </a>
      <a
        href={`https://dexscreener.com/solana/${mint}`}
        target="_blank"
        rel="noopener noreferrer"
        title="Open on DexScreener"
        className={link}
      >
        DEX
      </a>
      <a
        href={`https://solscan.io/token/${mint}`}
        target="_blank"
        rel="noopener noreferrer"
        title="Open on Solscan"
        className={link}
      >
        Solscan
      </a>
      {/* Rendered unavailable rather than omitted or faked. The paper wallet
          has no engine yet, and a button that silently does nothing is worse
          than one that says why it cannot. */}
      <span
        aria-disabled
        title="Paper trading is not built yet. No position can be opened."
        className="cursor-not-allowed rounded px-1.5 py-1 text-xs text-ink-faint/40"
      >
        Paper trade
      </span>
    </div>
  );
}

export function RadarRow({ entry, rank }: { entry: RadarEntry; rank: number }) {
  const risk = riskLabel(entry.risk_band);
  const rate = baseRateSummary(entry.base_rate);
  const change = entry.market?.change_24h_pct ?? null;
  const { primary, secondary } = tokenNaming(entry);
  // When the sentence is *about* the signal it already names it, and adds the
  // timing on top: "Recently graduated from Pump.fun" beside "Graduated from
  // Pump.fun 1 hour ago." is one fact printed twice. Keyed on the code the
  // backend sends, never on matching the prose.
  const signalIsTheSentence = entry.why_now?.code.startsWith("signal:") ?? false;

  return (
    <article className="rounded-card border border-line bg-surface/40 p-4 transition-colors hover:border-line-bright">
      {/* Identity and verdict. The two things scanned first, on one line. */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 items-center gap-3">
          <span className="w-5 shrink-0 text-right text-sm tabular-nums text-ink-faint">
            {rank}
          </span>
          <TokenAvatar mint={entry.mint_address} size={28} />
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <Link
              href={`/tokens/${entry.mint_address}`}
              className="truncate text-sm font-medium text-ink hover:underline"
            >
              {primary}
            </Link>
            {secondary ? (
              <span className="truncate text-xs text-ink-faint">{secondary}</span>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-4">
          {entry.signal && !signalIsTheSentence ? (
            <span
              className="rounded-chip border border-plasma/25 bg-plasma/[0.07] px-2 py-0.5 text-xs text-plasma"
              title={`Expires in ${expiresIn(entry.signal.expires_in_seconds) ?? "—"}`}
            >
              {entry.signal.label}
            </span>
          ) : null}
          <EvidenceDots evidence={entry.evidence} />
          <span
            className={cn(
              "text-xs",
              risk?.tone === "safe" && "text-safe",
              risk?.tone === "warn" && "text-warn",
              risk?.tone === "danger" && "text-danger",
              !risk && "text-ink-faint",
            )}
            title={
              risk
                ? entry.risk_reasons.join(" · ") || undefined
                : "Risk was not assessed for this row."
            }
          >
            {risk ? `${risk.label} risk` : "Risk —"}
          </span>
          <span className="text-xl font-semibold tabular-nums text-ink" title="Radar score">
            {Number(entry.opportunity_score).toFixed(0)}
          </span>
        </div>
      </div>

      {/* Why now. One sentence, rendered by the backend, on every row. */}
      {entry.why_now ? (
        <p className="mt-2.5 flex flex-wrap items-baseline gap-x-2 pl-8 text-sm text-ink-dim">
          <span>{entry.why_now.sentence}</span>
          {/* A signal is a statement with a shelf life. When the chip is
              suppressed as duplication, its expiry still has to survive. */}
          {entry.signal && signalIsTheSentence ? (
            <span className="text-xs text-ink-faint">
              Expires in {expiresIn(entry.signal.expires_in_seconds) ?? "—"}
            </span>
          ) : null}
        </p>
      ) : null}

      {/* The market strip. Dashes where nothing was observed — never zeroes. */}
      <div className="mt-3 grid grid-cols-3 gap-x-4 gap-y-3 pl-8 sm:grid-cols-4 lg:grid-cols-8">
        {/* The reading's own timestamp rides on the price rather than on a
            "liveness" chip. Sprint 24 removed that chip as internal
            vocabulary, and dropping the fact with it would have made a stale
            row indistinguishable from a live one. */}
        <Cell
          label="Price"
          value={compactUsd(entry.market?.price_usd)}
          title={
            entry.market?.captured_at
              ? `Last observed ${new Date(entry.market.captured_at).toLocaleString()}`
              : "Never observed."
          }
        />
        <Cell label="Mkt cap" value={compactUsd(entry.market?.market_cap)} />
        <Cell label="Liquidity" value={compactUsd(entry.market?.liquidity_usd)} />
        <Cell label="Vol 24h" value={compactUsd(entry.market?.volume_24h)} />
        <Cell
          label="Chg 24h"
          value={signedPct(change)}
          tone={changeTone(change)}
          title={
            change === null
              ? "No reading from a full 24 hours back. Not shown as 0%."
              : undefined
          }
        />
        <Cell label="Age" value={compactAge(entry.age_seconds)} />
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

      {/* The base rate, given its own block. This is the moat, and it spent
          Sprint 23 as the quietest line on the row. */}
      {rate ? (
        <div className="mt-3.5 ml-8 rounded-card border border-line/70 bg-elevated/30 px-3 py-2.5">
          <p className="text-label uppercase tracking-wide text-ink-faint">
            Similar historical signals
          </p>
          {rate.quotable ? (
            <div className="mt-1.5 flex flex-wrap items-baseline gap-x-5 gap-y-1">
              <span className="text-sm text-ink">{rate.headline}</span>
              {rate.lines.map((line) => (
                <span key={line} className="text-sm tabular-nums text-ink-dim">
                  {line}
                </span>
              ))}
              <span className="text-xs tabular-nums text-ink-faint">
                Median peak {formatMultiple(entry.base_rate?.median_peak_multiple)}
              </span>
              <span className="text-xs tabular-nums text-ink-faint">
                Median now {formatMultiple(entry.base_rate?.median_current_multiple)}
              </span>
            </div>
          ) : (
            <p className="mt-1.5 text-sm text-ink-faint">{rate.lines[0]}</p>
          )}
        </div>
      ) : null}

      <div className="mt-3 flex justify-end pl-8">
        <RowActions mint={entry.mint_address} />
      </div>
    </article>
  );
}
