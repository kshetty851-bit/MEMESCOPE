"use client";

import { useMemo } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Label, Panel } from "@/components/ui/panel";
import { AGENTS } from "@/lib/design/agents";
import { tokenNarrative, type Statement } from "@/lib/sentinel";
import { STATUS_MESSAGE } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { ScoreStatus, TokenScore } from "@/types/score";

/**
 * SENTINEL — the read on one token.
 *
 * The detail view is the only place the engine's `reasons` and component
 * breakdown exist: the ranking endpoint omits both, because a list is scanned
 * rather than read. So this is the only surface where Sentinel can name a
 * specific signal or a specific change — and it does so from the payload
 * `useTokenScore()` had already fetched, not one of its own.
 *
 * The sentences are the backend's, rendered from its reason codes. This
 * component orders and presents them; it does not write them. Where the token
 * has no score at all, it says which of the engine's states applies rather than
 * filling the space with something reassuring.
 */
const TONE_COLOUR: Record<Statement["tone"], string> = {
  neutral: "var(--color-ink-faint)",
  positive: "var(--color-safe)",
  caution: "var(--color-warn)",
  critical: "var(--color-danger)",
};

export function SentinelRead({
  score,
  status,
  isPending = false,
  className,
}: {
  score: TokenScore | null;
  status: ScoreStatus | undefined;
  /** The score query is still in flight — distinct from having no score. */
  isPending?: boolean;
  className?: string;
}) {
  const statements = useMemo(() => (score ? tokenNarrative(score) : []), [score]);

  return (
    <Panel
      accent={AGENTS.sentinel.hue}
      density="flush"
      className={cn("overflow-visible", className)}
    >
      <div className="flex items-center gap-3 border-b border-line p-4">
        <span
          className="flex size-9 shrink-0 items-center justify-center rounded-card border"
          style={{
            color: AGENTS.sentinel.hue,
            borderColor: `color-mix(in oklch, ${AGENTS.sentinel.hue} 30%, transparent)`,
            background: `color-mix(in oklch, ${AGENTS.sentinel.hue} 9%, transparent)`,
          }}
        >
          <AgentSigil agent="sentinel" size={20} alive />
        </span>
        <div className="min-w-0">
          <p
            className="text-sm font-semibold tracking-[0.12em]"
            style={{ color: AGENTS.sentinel.hue }}
          >
            SENTINEL
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">Operator read</p>
        </div>
      </div>

      <div className="p-4" aria-live="polite">
        {isPending ? (
          /* "Still fetching" and "there is nothing to say" are different
             claims, and rendering the second while the first is true told the
             user the engine had no opinion when it simply had not answered
             yet. */
          <p className="flex items-center gap-2 text-sm text-ink-faint">
            <span className="flex gap-1" aria-hidden>
              {[0, 1, 2].map((index) => (
                <span
                  key={index}
                  className="motion-loop size-1.5 rounded-full bg-ink-faint animate-[breathe_1.8s_ease-in-out_infinite]"
                  style={{ animationDelay: `${index * 0.22}s` }}
                />
              ))}
            </span>
            Reading the engine output
          </p>
        ) : statements.length === 0 ? (
          <p className="text-sm text-ink-faint">
            {/* An unscored token is a backend state, not an error, and each
                state has its own sentence. Saying "no data" for all of them
                would discard the distinction the API went to the trouble of
                making. */}
            {(status && STATUS_MESSAGE[status]) ??
              "No readout available for this token yet."}
          </p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {statements.map((statement, index) => (
              <li
                key={statement.id}
                className="flex gap-2.5 text-sm leading-relaxed text-ink-dim animate-[rise_0.5s_var(--ease-instrument)_both]"
                style={{ animationDelay: `${Math.min(index * 60, 300)}ms` }}
              >
                <span
                  aria-hidden
                  className="mt-[7px] size-1.5 shrink-0 rounded-full"
                  style={{ background: TONE_COLOUR[statement.tone] }}
                />
                <span className="min-w-0">{statement.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-line px-4 py-3">
        <Label>Interpretation of engine output — not independent analysis</Label>
      </div>
    </Panel>
  );
}
