"use client";

import { Panel } from "@/components/ui/panel";
import { Portrait } from "@/components/hq/portrait";
import { EMPLOYEE_BY_ID } from "@/lib/hq/employees";
import { ideasFrom, type Idea, type Urgency } from "@/lib/hq/ideas";
import type { HqState } from "@/lib/hq/adapter";

/**
 * IDEAS FROM THE FLOOR.
 *
 * Each card is a desk proposing work on the thing that desk measures, and
 * every one shows the reading it came from — the figure and the field. That
 * pairing is the whole design: a suggestion a reader cannot check is a
 * suggestion this product has no business making.
 *
 * ── AN EMPTY BOARD IS A RESULT ──────────────────────────────────────────
 *
 * When nothing crosses a threshold this renders one sentence saying so. It
 * does not fall back to generic advice, and it does not hold space with
 * skeletons: the honest reading of "no ideas" is that the desks with evidence
 * have nothing to raise, and dressing that up would undo the point.
 */

const URGENCY_COLOR: Record<Urgency, string> = {
  now: "var(--color-down)",
  soon: "var(--color-warn)",
  "worth doing": "var(--color-ink-3, var(--color-ink))",
};

function IdeaCard({ idea }: { idea: Idea }) {
  const who = EMPLOYEE_BY_ID.get(idea.from);
  return (
    <article
      className="flex gap-3 border-t border-[var(--color-line)] py-3 first:border-t-0"
      data-testid="hq-idea"
      data-idea={idea.id}
    >
      <Portrait id={idea.from} size={34} />
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-xs font-semibold text-[var(--color-ink)]">{idea.headline}</span>
          <span
            className="font-mono text-[10px] uppercase tracking-wide"
            style={{ color: URGENCY_COLOR[idea.urgency] }}
          >
            {idea.urgency}
          </span>
        </div>
        {/* The evidence. Deliberately the same visual weight as the idea
            itself — it is not a footnote, it is the reason the card exists. */}
        <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
          {idea.because}
        </p>
        <p className="text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
          {who?.name ?? idea.from} · <span className="font-mono">{idea.source}</span>
        </p>
      </div>
    </article>
  );
}

export function IdeasPanel({ state }: { state: HqState }) {
  const ideas = ideasFrom(state);
  return (
    <Panel>
      <section className="flex flex-col gap-2 p-4" aria-label="Ideas from the floor">
        <header className="flex flex-col gap-0.5">
          <h2 className="text-sm font-semibold text-[var(--color-ink)]">Ideas from the floor</h2>
          <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
            What each desk would work on next, and the reading it is arguing
            from. Nothing appears here without a measured figure behind it.
          </p>
        </header>
        <div className="flex flex-col">
          {ideas.length === 0 ? (
            <p className="py-3 text-xs text-[var(--color-ink-3,var(--color-ink))]">
              Nothing to raise. Every desk with a current reading is below the
              line it would speak up at — which is a result, not an empty panel.
            </p>
          ) : (
            ideas.map((idea) => <IdeaCard key={idea.id} idea={idea} />)
          )}
        </div>
      </section>
    </Panel>
  );
}
