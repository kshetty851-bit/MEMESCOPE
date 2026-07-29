"use client";

import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Badge } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { AGENTS, ALL_AGENTS } from "@/lib/design/agents";
import { BUILD } from "@/lib/env";
import { GRADE_LABEL, GRADE_TONE } from "@/lib/scores";
import type { ScoreGrade } from "@/types/score";

/**
 * ABOUT
 *
 * The trust surface. An alpha tester is being asked to act on a number a
 * machine produced about a brand-new token, so the product has to be able to
 * answer three questions without being asked: what is this, how did it decide,
 * and what does it not know.
 *
 * The last one carries the most weight. Every figure here — the weights, the
 * bands, the unavailable signals — is stated because it is already true and
 * published at `/api/v1/scores/model`; nothing on this page is a promise.
 *
 * Inside the dashboard route group so it inherits the shell and the reader can
 * get back to the instrument in one click.
 */

const BANDS: { grade: ScoreGrade; range: string; meaning: string }[] = [
  {
    grade: "critical",
    range: "under 30",
    meaning: "Failed the risk gate, or scored too low to consider.",
  },
  {
    grade: "weak",
    range: "30 – 49",
    meaning: "Nothing disqualifying, nothing compelling. Most tokens land here.",
  },
  {
    grade: "watch",
    range: "50 – 64",
    meaning: "Something is working. Not yet enough to act on.",
  },
  {
    grade: "strong",
    range: "65 – 79",
    meaning: "Several signals agree. Worth your attention.",
  },
  {
    grade: "high_conviction",
    range: "80 and above",
    meaning: "The strongest reading the model produces. Rare.",
  },
];

const SIGNALS_LIVE = [
  ["Liquidity depth", "How much can be traded before the price moves."],
  ["Momentum", "Rate of price change against its own recent baseline."],
  ["Trade flow", "The balance of buys against sells."],
  ["Valuation structure", "Whether market cap and supply are consistent."],
  ["Survival age", "How long the token has lasted since launch."],
];

const SIGNALS_MISSING = [
  ["Contract safety", "Mint and freeze authority, LP burn, renouncement."],
  ["Holder distribution", "Concentration across wallets."],
  ["Smart money", "Whether wallets with a record are buying."],
  ["Narrative", "What is being said about it."],
];

export default function AboutPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 pb-8">
      <header>
        <Label>About</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          What LETZMOON is, and what it is not
        </h1>
        <p className="mt-3 text-ink-dim">
          LETZMOON watches Solana for newly launched tokens, gathers market data on each
          one, and scores it with a deterministic engine. The point is to see something
          worth seeing earlier — and to be told plainly how much the platform actually
          knows.
        </p>
      </header>

      {/* --- The problem ---------------------------------------------------- */}
      <Panel>
        <Label>The problem</Label>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          Thousands of tokens launch on Solana every day. Almost all of them go nowhere and
          a meaningful number are designed to take your money. By the time a token is
          visible enough to hear about, the move has usually happened. Checking each one by
          hand means reading liquidity, trade flow and supply structure across several
          tools, for every candidate, all day.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          LETZMOON does that continuously and shows its work.
        </p>
      </Panel>

      {/* --- Scoring -------------------------------------------------------- */}
      <section>
        <Label>What AI scoring means here</Label>
        <h2 className="mt-2 text-heading font-medium text-ink">
          A transparent model, not a black box
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          There is no language model and no neural network in the scoring path. The engine
          is a weighted model over measurable features: each signal is scored, weighted, and
          added up, and every score can be decomposed back into the contributions that
          produced it. You can see that breakdown on any token page.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          This is a deliberate choice. A model trained to predict which tokens succeed would
          need a history of which ones did, and the platform has not been collecting long
          enough to have one. A model trained anyway would dress up guesses as rigour. The
          current weights are <span className="text-ink">stated priors</span>, published in
          full at{" "}
          <code className="rounded-chip bg-surface px-1 py-0.5 font-mono text-xs">
            /api/v1/scores/model
          </code>
          , so the claim is checkable rather than asserted.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          Scoring is also <span className="text-ink">deterministic</span>: the same stored
          data and the same model version always produce the same score. Two people looking
          at one token see one number.
        </p>
      </section>

      {/* --- Grades --------------------------------------------------------- */}
      <section>
        <Label>Reading a grade</Label>
        <h2 className="mt-2 text-heading font-medium text-ink">What the bands mean</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[30rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="pb-2 pr-4 font-medium text-ink-faint">Grade</th>
                <th className="pb-2 pr-4 font-medium text-ink-faint">Score</th>
                <th className="pb-2 font-medium text-ink-faint">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {BANDS.map((band) => (
                <tr key={band.grade} className="border-b border-line/40 last:border-0">
                  <td className="py-2.5 pr-4 align-top">
                    <span
                      className="whitespace-nowrap font-medium"
                      style={{ color: GRADE_TONE[band.grade] }}
                    >
                      {GRADE_LABEL[band.grade]}
                    </span>
                  </td>
                  <td data-numeric className="py-2.5 pr-4 align-top text-ink-dim">
                    {band.range}
                  </td>
                  <td className="py-2.5 align-top text-ink-dim">{band.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm leading-relaxed text-ink-dim">
          A grade is not a recommendation. It says how the token reads against the signals
          available right now.
        </p>
      </section>

      {/* --- Confidence ----------------------------------------------------- */}
      <section>
        <Label>Confidence, coverage and evidence</Label>
        <h2 className="mt-2 text-heading font-medium text-ink">
          The most important thing on the screen
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          A score of 80 built on two signals is not the same as a score of 80 built on nine.
          Three figures keep those apart:
        </p>
        <dl className="mt-4 flex flex-col gap-3 text-sm">
          <div>
            <dt className="font-medium text-ink">Coverage</dt>
            <dd className="mt-0.5 text-ink-dim">
              How much of the model could actually be applied. Signals with no data source
              count against it rather than being quietly dropped.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-ink">Evidence</dt>
            <dd className="mt-0.5 text-ink-dim">
              Coverage combined with how many observations the token has. A token seen twice
              supports less than one seen fifty times.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-ink">Confidence</dt>
            <dd className="mt-0.5 text-ink-dim">
              Evidence discounted by how stale the latest observation is. Confidence falls
              on its own if a token stops being updated.
            </dd>
          </div>
        </dl>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Panel density="compact">
            <Label>Signals in use</Label>
            <ul className="mt-2.5 flex flex-col gap-2">
              {SIGNALS_LIVE.map(([name, detail]) => (
                <li key={name} className="text-sm">
                  <span className="text-ink">{name}</span>
                  <span className="block text-xs text-ink-faint">{detail}</span>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel density="compact" accent="var(--color-warn)">
            <Label>Declared but unavailable</Label>
            <ul className="mt-2.5 flex flex-col gap-2">
              {SIGNALS_MISSING.map(([name, detail]) => (
                <li key={name} className="text-sm">
                  <span className="text-ink-dim">{name}</span>
                  <span className="block text-xs text-ink-faint">{detail}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <p className="mt-4 text-sm leading-relaxed text-ink-dim">
          Those four have no data source yet. They are declared with real weight and counted
          against coverage, which is why confidence across the feed currently reads low —
          and why <span className="text-apex">no token can be certified Elite</span> at
          present. That is the mechanism working, not a fault.
        </p>
      </section>

      {/* --- Sentinel ------------------------------------------------------- */}
      <section>
        <Label>Sentinel</Label>
        <h2 className="mt-2 flex items-center gap-2.5 text-heading font-medium text-ink">
          <span style={{ color: AGENTS.sentinel.hue }}>
            <AgentSigil agent="sentinel" size={20} />
          </span>
          The operator who reads the instrument for you
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          Sentinel turns the engine&rsquo;s output into sentences: what the window looks
          like, which token leads it, which carries the most risk, and how much of the model
          was available. On a token page it explains what moved and which signals were
          missing.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          Sentinel is a <span className="text-ink">narrator, not a second analyst</span>. It
          never calculates a score, never applies a threshold of its own, and never says
          anything the engine did not already conclude. If Sentinel and a number on screen
          ever disagree, that is a bug — please report it.
        </p>
      </section>

      {/* --- Division ------------------------------------------------------- */}
      <section>
        <Label>The division</Label>
        <p className="mt-2 text-sm leading-relaxed text-ink-dim">
          Seven specialists, each owning one part of the readout. A panel with no data
          source says so rather than filling the space.
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {ALL_AGENTS.map((id) => {
            const spec = AGENTS[id];
            return (
              <div key={id} className="flex items-start gap-2.5">
                <span className="mt-0.5 shrink-0" style={{ color: spec.hue }}>
                  <AgentSigil agent={id} size={16} />
                </span>
                <p className="text-sm">
                  <span className="font-medium" style={{ color: spec.hue }}>
                    {spec.name}
                  </span>
                  <span className="text-ink-faint"> — {spec.mission}</span>
                </p>
              </div>
            );
          })}
        </div>
      </section>

      {/* --- Alpha disclaimer ----------------------------------------------- */}
      <Panel accent="var(--color-warn)">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="warn">Private alpha</Badge>
          <span data-numeric className="font-mono text-xs text-ink-faint">
            v{BUILD.version} · {BUILD.sha}
          </span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          This is early software shown to a small group. Expect gaps: four of the nine
          signals are not yet collected, Elite certification is unreachable, and scores will
          change as the model improves. Data may be reset during the alpha.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">
          <span className="text-ink">
            LETZMOON is an intelligence tool, not financial advice.
          </span>{" "}
          Nothing here is a recommendation to buy or sell anything. Meme coins routinely go
          to zero. Do your own research, and never risk money you cannot afford to lose.
        </p>
        <p className="mt-3 text-sm text-ink-faint">
          Found something wrong, confusing, or missing? Use the feedback button — it is the
          entire point of this phase.
        </p>
      </Panel>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/command"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          ← Back to the Command Center
        </Link>
      </div>
    </div>
  );
}
