"use client";

import Link from "next/link";

import { CloneRiskBadge } from "@/components/decision/clone-risk-badge";
import { ConvictionBadge } from "@/components/decision/conviction-badge";
import { Panel } from "@/components/ui/panel";
import { componentLabel, leadingComponents } from "@/lib/thesis";
import { cn } from "@/lib/utils";
import type { TokenIdentity } from "@/types/identity";
import type { RadarEntry } from "@/types/radar";
import type { TokenScore } from "@/types/score";

/**
 * One opportunity, as a card that answers its own question.
 *
 * The old token card led with a score and a grade. This one leads with the
 * conviction band, then the two or three signals that actually drove it, then
 * the risks. A user should be able to read a card and know why it is on their
 * screen without opening anything.
 *
 * Every line is backend-sourced: the band comes from the engine's grade, the
 * supporting signals are the engine's own components ordered by the
 * contribution it calculated, and the clone sentence is rendered by
 * `services/identity.py`.
 */
/** The Radar's own category names, for cards the engine ranking does not cover. */
const RADAR_CATEGORY_LABEL: Record<string, string> = {
  early_momentum: "Early Momentum",
  breakout: "Breakout",
  undervalued: "Undervalued",
  elite: "Elite",
  strong_community: "Strong Community",
};

export function OpportunityCard({
  mint,
  name,
  symbol,
  score,
  radar,
  identity,
  className,
}: {
  mint: string;
  name?: string | null;
  symbol?: string | null;
  score?: TokenScore | null;
  radar?: RadarEntry | null;
  identity?: TokenIdentity;
  className?: string;
}) {
  const leading = leadingComponents(score?.components, 3);
  const multiple = radar?.current_multiple ? Number(radar.current_multiple) : null;
  const confidence = score?.evidence?.confidence;

  return (
    <Panel density="compact" interactive className={cn("group", className)}>
      <Link href={`/tokens/${mint}`} className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">
              {symbol ?? name ?? (
                <span data-numeric className="font-mono">
                  {mint.slice(0, 4)}…{mint.slice(-4)}
                </span>
              )}
            </p>
            {name && symbol && name !== symbol ? (
              <p className="mt-0.5 truncate text-xs text-ink-faint">{name}</p>
            ) : null}
          </div>

          {score ? (
            <ConvictionBadge
              grade={score.grade}
              isElite={score.is_elite}
              score={score.score}
              showWhy={false}
              className="shrink-0 items-end"
            />
          ) : radar ? (
            // The engine's ranking window does not extend to every Radar entry,
            // so a token can be on the Radar without a current engine score in
            // view. Showing the Radar's own category instead — attributed, so
            // the two are never mistaken for each other — beats a blank space
            // that reads as "nothing known".
            <span className="shrink-0 text-right">
              <span className="block text-sm font-medium tracking-tight text-oracle">
                {RADAR_CATEGORY_LABEL[radar.category] ?? radar.category}
              </span>
              <span className="block text-[0.625rem] uppercase tracking-[0.08em] text-ink-faint">
                Radar
              </span>
            </span>
          ) : null}
        </div>

        {/* What actually drove the band. Three signals, engine-ordered. */}
        {leading.length > 0 ? (
          <ul className="flex flex-col gap-1">
            {leading.map((component) => (
              <li key={component.id} className="flex items-center gap-2 text-xs text-ink-dim">
                <span
                  aria-hidden
                  className="h-1 w-1 shrink-0 rounded-full bg-safe/70"
                />
                {componentLabel(component.id)}
              </li>
            ))}
          </ul>
        ) : null}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line/50 pt-2.5">
          {multiple !== null ? (
            <span className="text-xs text-ink-dim">
              <span className="text-ink-faint">Since found </span>
              <span data-numeric className="font-mono tabular-nums">
                {multiple.toFixed(2)}×
              </span>
            </span>
          ) : null}

          {confidence ? (
            <span className="text-xs text-ink-dim">
              <span className="text-ink-faint">Confidence </span>
              <span data-numeric className="font-mono tabular-nums">
                {Math.round(Number(confidence))}%
              </span>
            </span>
          ) : null}

          {score?.risk?.has_veto ? (
            <span className="text-xs font-medium text-danger">Vetoed by risk gate</span>
          ) : null}
        </div>

        {identity && identity.clone_risk !== "none" ? (
          <CloneRiskBadge identity={identity} showWhy={false} />
        ) : null}
      </Link>
    </Panel>
  );
}
