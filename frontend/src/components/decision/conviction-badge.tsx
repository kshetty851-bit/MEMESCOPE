"use client";

import {
  CONVICTION_MEANING,
  CONVICTION_TONE,
  convictionLabel,
  convictionOf,
} from "@/lib/conviction";
import { Why } from "@/components/decision/why";
import { cn } from "@/lib/utils";
import type { ScoreGrade } from "@/types/score";

/**
 * The conviction badge — words first, number second.
 *
 * Phase 12 inverts the old hierarchy. The score used to be the headline and the
 * grade a footnote; now the band is what the eye lands on and the number is a
 * secondary detail for anyone comparing two tokens precisely.
 *
 * The score is not hidden. Removing it would make the badge unfalsifiable, and
 * the whole posture of this product is that its claims stay checkable.
 */
export function ConvictionBadge({
  grade,
  isElite = false,
  score,
  size = "default",
  showWhy = true,
  className,
}: {
  grade: ScoreGrade;
  isElite?: boolean;
  /** The raw figure, shown small beside the band. */
  score?: string | null;
  size?: "default" | "large";
  showWhy?: boolean;
  className?: string;
}) {
  const conviction = convictionOf(grade, isElite);
  const tone = CONVICTION_TONE[conviction];

  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <span className="inline-flex items-baseline gap-2">
        <span
          className={cn(
            "font-medium tracking-tight",
            size === "large" ? "text-lg" : "text-sm",
          )}
          style={{ color: tone }}
        >
          {convictionLabel(grade, isElite)}
        </span>
        {score ? (
          <span
            data-numeric
            className="font-mono text-xs tabular-nums text-ink-faint"
            title="The engine's numeric score, 0–100"
          >
            {score}
          </span>
        ) : null}
      </span>
      {showWhy ? <Why>{CONVICTION_MEANING[conviction]}</Why> : null}
    </span>
  );
}
