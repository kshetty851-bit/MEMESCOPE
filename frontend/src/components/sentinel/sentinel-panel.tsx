"use client";

import { useMemo } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { StatusDot } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { AGENTS } from "@/lib/design/agents";
import {
  coverageBrief,
  missionBrief,
  opportunityBrief,
  summariseMarket,
  threatBrief,
  type Statement,
} from "@/lib/sentinel";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";
import type { TokenScore } from "@/types/score";

/**
 * SENTINEL — the operator's panel.
 *
 * The station has always shown what the engine concluded; this is where it says
 * it in a sentence. Sentinel reads the scoring window the page has already
 * loaded and narrates it — no request of its own, no opinion of its own. Every
 * line traces to a backend field or a backend-rendered string (see
 * `lib/sentinel.ts` for the rule that keeps it honest).
 *
 * Laid out as a brief followed by three readings, because that is the order an
 * analyst would speak in: here is the state of things, here is the best of it,
 * here is the worst of it, and here is how much to trust any of it.
 */

const TONE_COLOUR: Record<Statement["tone"], string> = {
  neutral: "var(--color-ink-faint)",
  positive: "var(--color-safe)",
  caution: "var(--color-warn)",
  critical: "var(--color-danger)",
};

export function SentinelPanel({
  tokens,
  scoresByMint,
  labelsByMint,
  totalScored,
  className,
}: {
  tokens: DiscoveredToken[];
  scoresByMint: Map<string, TokenScore>;
  labelsByMint: Map<string, string>;
  totalScored: number;
  className?: string;
}) {
  // Names come from the ranking response, which names every row it scores, with
  // the discovery feed as a second source for arrivals. A mint neither knows is
  // shown as a truncated address rather than given a label Sentinel made up.
  const labels = useMemo(() => {
    const map = new Map(labelsByMint);
    for (const token of tokens) {
      const label = token.symbol ?? token.name;
      if (label && !map.has(token.mint_address)) map.set(token.mint_address, label);
    }
    return map;
  }, [labelsByMint, tokens]);

  const brief = useMemo(
    () =>
      summariseMarket(scoresByMint, labels, {
        discovered: tokens.length,
        totalScored,
      }),
    [scoresByMint, labels, tokens.length, totalScored],
  );

  const mission = useMemo(() => missionBrief(brief), [brief]);
  const opportunity = useMemo(() => opportunityBrief(brief), [brief]);
  const threat = useMemo(() => threatBrief(brief), [brief]);
  const coverage = useMemo(() => coverageBrief(brief), [brief]);

  const analysing = brief.scored === 0;

  return (
    <Panel
      accent={AGENTS.sentinel.hue}
      className={cn("overflow-visible", className)}
      density="flush"
    >
      {/* --- Header ------------------------------------------------------- */}
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

        <div className="min-w-0 flex-1">
          <p
            className="text-sm font-semibold tracking-[0.12em]"
            style={{ color: AGENTS.sentinel.hue }}
          >
            SENTINEL
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">Mission brief</p>
        </div>

        <span className="flex items-center gap-1.5">
          <StatusDot
            live={!analysing}
            tone={analysing ? "var(--color-ink-faint)" : "var(--color-safe)"}
          />
          <Label>{analysing ? "Analysing" : "Reading"}</Label>
        </span>
      </div>

      {/* --- Mission brief ------------------------------------------------
          `aria-live="polite"` because this text changes underneath a reader
          as the window refreshes; polite so it waits for a pause rather than
          interrupting. */}
      <div className="border-b border-line p-4" aria-live="polite" aria-atomic="false">
        {analysing ? <TypingIndicator /> : <StatementList statements={mission} />}
      </div>

      {/* --- Readings -----------------------------------------------------
          Held back entirely until there is a window to read. Rendering the
          threat reading beside an empty opportunity cell left a half-filled
          panel that looked like a loading failure rather than a system with
          nothing to report yet. */}
      {!analysing && (
        <>
          <div className="grid gap-px bg-line sm:grid-cols-2">
            <Reading title="Opportunity" statements={opportunity} className="bg-surface" />
            <Reading title="Threat" statements={threat} className="bg-surface" />
          </div>

          <div className="border-t border-line">
            <Reading title="Confidence and coverage" statements={coverage} />
          </div>
        </>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- Parts -- */

function Reading({
  title,
  statements,
  className,
}: {
  title: string;
  statements: Statement[];
  className?: string;
}) {
  if (statements.length === 0) return null;

  return (
    <section className={cn("p-4", className)}>
      <Label>{title}</Label>
      <div className="mt-2.5">
        <StatementList statements={statements} />
      </div>
    </section>
  );
}

function StatementList({ statements }: { statements: Statement[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {statements.map((statement, index) => (
        <li
          key={statement.id}
          className="flex gap-2.5 text-sm leading-relaxed text-ink-dim animate-[rise_0.5s_var(--ease-instrument)_both]"
          // Stagger reads as the operator working through the list rather than
          // the whole brief appearing at once. Capped so a long list never
          // leaves the last line waiting.
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
  );
}

/**
 * Sentinel is reading but has nothing to say yet.
 *
 * Three dots on a staggered `breathe`, which is opacity and transform only, so
 * it composites; `.motion-loop` means Command mode and reduced motion still it
 * rather than removing it, keeping the "working" state legible either way.
 */
function TypingIndicator() {
  return (
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
      Reading the scoring window
    </p>
  );
}
