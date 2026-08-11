"use client";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import type { Thesis } from "@/lib/thesis";

/**
 * Investment Thesis — the case, laid out.
 *
 * Six sections in a deliberate order: why it appeared, what supports it, what
 * argues against it, what could go wrong, what frames all of it, and what the
 * platform simply cannot see.
 *
 * The last section is the one that makes the rest trustworthy. Ending on
 * "here is what we do not know" is what separates an intelligence product from
 * a pitch, and it is why low confidence reads as honesty rather than a fault.
 *
 * Every sentence rendered here was produced by the backend. This component
 * chooses headings and order; it writes no prose of its own about any token.
 */
export function InvestmentThesis({ thesis }: { thesis: Thesis }) {
  return (
    <Panel density="comfortable" className="flex flex-col gap-5">
      <header className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium tracking-tight text-ink">Investment thesis</h2>
        <Why label="What is this?">
          The observable case for and against this token, assembled from what the
          scoring engine, the Radar and Exit Watch each reported. It is not a
          recommendation, and MEMESCOPE has no view on whether you should act.
        </Why>
      </header>

      {thesis.appeared.length > 0 ? (
        <Section title="Why it appeared">
          <ul className="flex flex-col gap-1.5">
            {thesis.appeared.map((reason) => (
              <li key={reason} className="text-sm leading-relaxed text-ink-2">
                {reason}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <PointList title="Supporting evidence" points={thesis.strengths} tone="var(--color-up)" />
      <PointList title="Weaknesses" points={thesis.weaknesses} tone="var(--color-ink-2)" />
      <PointList title="Current risks" points={thesis.risks} tone="var(--color-down)" />
      <PointList title="Context" points={thesis.context} tone="var(--color-ink-3)" />

      {thesis.unavailable.length > 0 ? (
        <Section title="Not collected">
          <p className="text-sm leading-relaxed text-ink-2">
            MEMESCOPE cannot see {joinNaturally(thesis.unavailable)} for any token
            yet. These are declared in the model and counted against confidence
            rather than assumed to be fine, so a low confidence figure here
            describes the platform&rsquo;s coverage — not this project.
          </p>
        </Section>
      ) : null}
    </Panel>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-label font-medium uppercase text-ink-3">
        {title}
      </h3>
      {children}
    </section>
  );
}

function PointList({
  title,
  points,
  tone,
}: {
  title: string;
  points: Thesis["strengths"];
  tone: string;
}) {
  if (points.length === 0) return null;

  return (
    <Section title={title}>
      <ul className="flex flex-col gap-2">
        {points.map((point) => (
          <li key={point.code} className="flex gap-2.5 text-sm leading-relaxed text-ink-2">
            <span
              aria-hidden
              className="mt-[0.4375rem] h-1 w-1 shrink-0 rounded-full"
              style={{ background: tone }}
            />
            <span>
              {point.message}
              {point.agent ? (
                <span className="ml-2 text-label uppercase text-ink-3">
                  {point.agent}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** "a, b and c" — reads as a sentence rather than a dumped array. */
function joinNaturally(items: string[]): string {
  const lower = items.map((item) => item.toLowerCase());
  const last = lower.at(-1) ?? "";
  if (lower.length === 1) return last;
  return `${lower.slice(0, -1).join(", ")} or ${last}`;
}
