"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import { type Change, diffToken, lastVisitAt, rememberedTokens } from "@/lib/changes";
import type { RadarEntry } from "@/types/radar";
import type { TokenScore } from "@/types/score";

/**
 * Since your last visit.
 *
 * The point of this panel is subtraction, not addition. A user returning to a
 * feed of thousands of tokens cannot tell what is new, so the platform has to
 * tell them — and it earns that trust by staying quiet when nothing material
 * moved. Anything that reports "12 updates" every time you blink gets ignored
 * within a week.
 *
 * Materiality is not decided here: `diffToken` reuses the engine's own
 * threshold for what counts as a real score movement, so this panel and the
 * scoring history agree about what "changed" means.
 *
 * The memory is per-browser. That is stated in the panel rather than implied,
 * because a user who clears their storage will otherwise think the platform
 * forgot them.
 */
export function SinceLastVisit({
  scores,
  radar,
  exitSeverity,
}: {
  scores: Map<string, TokenScore>;
  radar: Map<string, RadarEntry>;
  exitSeverity: Map<string, string>;
}) {
  // Read once per mount. Re-reading on every render would diff against memory
  // this same page just wrote and report nothing forever.
  const [baseline] = useState(() => ({
    at: lastVisitAt(),
    tokens: rememberedTokens(),
  }));

  const changed = useMemo(() => {
    const rows: { mint: string; changes: Change[] }[] = [];

    for (const [mint, before] of Object.entries(baseline.tokens)) {
      const score = scores.get(mint);
      const entry = radar.get(mint);
      if (!score && !entry) continue;

      const changes = diffToken(before, {
        score: score ? Number(score.score) : null,
        grade: score?.grade ?? null,
        liquidity: entry?.current_liquidity ? Number(entry.current_liquidity) : null,
        volume24h: null,
        currentMultiple: entry?.current_multiple ? Number(entry.current_multiple) : null,
        exitSeverity: exitSeverity.get(mint) ?? null,
      });

      if (changes.length > 0) rows.push({ mint, changes });
    }

    return rows.slice(0, 8);
  }, [baseline, scores, radar, exitSeverity]);

  if (!baseline.at) {
    return (
      <Panel density="compact" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium tracking-tight text-ink">First visit</h2>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
          MEMESCOPE will remember what you saw today and show you what moved
          when you come back. That memory is stored in this browser only — there
          is no account behind it yet, so clearing your browser data resets it.
        </p>
      </Panel>
    );
  }

  if (changed.length === 0) {
    return (
      <Panel density="compact" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium tracking-tight text-ink">
          Since your last visit
        </h2>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
          Nothing you were shown has moved by more than the engine treats as
          material. Silence here is a reading, not a failure to check.
        </p>
      </Panel>
    );
  }

  return (
    <Panel density="comfortable" className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium tracking-tight text-ink">
          Since your last visit
        </h2>
        <Why>
          Only movements past the engine&rsquo;s own materiality threshold are
          listed, so this panel stays quiet unless something genuinely changed.
          The comparison is against what this browser last showed you.
        </Why>
      </header>

      <ul className="flex flex-col divide-y divide-line/50">
        {changed.map(({ mint, changes }) => {
          const entry = radar.get(mint);
          const label = entry?.symbol ?? entry?.name ?? `${mint.slice(0, 4)}…${mint.slice(-4)}`;

          return (
            <li key={mint} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
              <Link
                href={`/tokens/${mint}`}
                className="text-sm font-medium text-ink hover:text-oracle"
              >
                {label}
              </Link>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {changes.map((change) => (
                  <li key={change.code} className="text-xs text-ink-dim">
                    <span className="text-ink-faint">{change.label} </span>
                    <span
                      data-numeric
                      className="font-mono tabular-nums"
                      style={{
                        color:
                          change.direction === "up"
                            ? "var(--color-safe)"
                            : change.direction === "down"
                              ? "var(--color-danger)"
                              : "var(--color-ink-dim)",
                      }}
                    >
                      {change.display}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
