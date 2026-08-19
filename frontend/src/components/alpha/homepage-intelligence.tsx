import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { AGENTS, ALL_AGENTS, type AgentId } from "@/lib/design/agents";

type AnalystBrief = {
  signals: string;
  detail: string;
  status: "Active readout" | "Declared signal lane";
};

// This page is deliberately static: it introduces the product without creating
// another client-side data path or making a marketing view depend on live APIs.
// Each description is constrained to the currently registered model/components.
const ANALYST_BRIEFS: Record<AgentId, AnalystBrief> = {
  scout: {
    signals: "Launch age · active window",
    detail: "Tracks newly discovered tokens through their opening and active windows.",
    status: "Active readout",
  },
  titan: {
    signals: "Holder distribution · smart money",
    detail: "The model reserves this lane for large-flow and holder evidence; those inputs are not yet available.",
    status: "Declared signal lane",
  },
  pulse: {
    signals: "Momentum · trade flow",
    detail: "Measures acceleration, buy and sell pressure, participation, and the quality of the observed trend.",
    status: "Active readout",
  },
  echo: {
    signals: "Narrative · social attention",
    detail: "The model declares a narrative lane, but its source signal is not yet available.",
    status: "Declared signal lane",
  },
  sentinel: {
    signals: "Liquidity depth · market state",
    detail: "Reads liquidity structure, withdrawals, pool activity, and unresolved market state. Contract safety remains a declared future input.",
    status: "Active readout",
  },
  oracle: {
    signals: "Valuation · evidence coverage",
    detail: "Combines available evidence, valuation structure, history, and coverage into a bounded confidence reading.",
    status: "Active readout",
  },
  apex: {
    signals: "Sustained Elite criteria",
    detail: "Records Elite classification only when the configured criteria are met and sustained.",
    status: "Active readout",
  },
};

const PIPELINE = [
  ["Detect", "Capture newly discovered Pump.fun tokens."],
  ["Enrich", "Append observable market and liquidity snapshots."],
  ["Analyze", "Evaluate available market, lifecycle, and evidence signals."],
  ["Rank", "Publish the Radar's single server-owned ordering."],
  ["Monitor", "Keep a permanent observation and detection record."],
  ["Simulate", "Run Paper Wallet rules against stored market observations."],
  ["Verify risk", "Record a fail-closed safety decision before any future real execution."],
] as const;

const PRODUCT_LINKS = [
  { href: "/command", title: "Open Radar", body: "Review ranked Radar candidates and fresh detections." },
  { href: "/record", title: "View track record", body: "Inspect every recorded detection, including outcomes that did not work." },
  { href: "/wallet", title: "Open Paper Wallet", body: "Follow the simulated strategy and its immutable trade record." },
] as const;

export function HomepageIntelligence() {
  return (
    <div className="relative z-10 border-t border-line/70 bg-abyss/92 text-ink">
      <section className="mx-auto max-w-[1120px] px-6 py-24 md:py-32">
        <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">
          MEMESCOPE intelligence platform
        </p>
        <div className="mt-5 grid gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div>
            <h2 className="max-w-3xl text-4xl font-medium tracking-[-0.045em] text-ink sm:text-5xl">
              See the signal before the crowd.
            </h2>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-ink-dim">
              Real-time token intelligence built to detect, analyze, and rank emerging
              opportunities across the Pump.fun ecosystem.
            </p>
          </div>
          <p className="max-w-md border-l border-plasma/45 pl-5 text-sm leading-6 text-ink-faint">
            Scan the noise. Understand the risk. Find the signal. MEMESCOPE surfaces
            evidence and records uncertainty—it does not promise outcomes.
          </p>
        </div>
      </section>

      <section className="border-y border-line/70 bg-surface/[0.28]">
        <div className="mx-auto max-w-[1120px] px-6 py-20 md:py-24">
          <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">
            From detection to decision
          </p>
          <div className="mt-5 flex flex-wrap items-end justify-between gap-6">
            <h2 className="max-w-xl text-3xl font-medium tracking-[-0.04em] text-ink sm:text-4xl">
              Thousands of tokens compete for attention. MEMESCOPE organizes observable
              market activity into structured intelligence.
            </h2>
            <p className="max-w-sm text-sm leading-6 text-ink-faint">
              Every stage is explicit so a missing or stale input remains visible instead
              of being treated as a positive signal.
            </p>
          </div>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-panel border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE.map(([title, detail], index) => (
              <li key={title} className="min-h-40 bg-abyss/95 p-5">
                <span className="text-label text-ink-faint">{String(index + 1).padStart(2, "0")}</span>
                <h3 className="mt-7 text-base font-medium text-ink">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-ink-faint">{detail}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-[1120px] px-6 py-24 md:py-32">
        <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">
          Meet the MEMESCOPE analysts
        </p>
        <div className="mt-5 flex flex-wrap items-end justify-between gap-6">
          <div>
            <h2 className="text-3xl font-medium tracking-[-0.04em] text-ink sm:text-4xl">
              One market. Multiple perspectives.
            </h2>
            <p className="mt-3 max-w-2xl text-base leading-7 text-ink-dim">
              Each division owns a specific evidence lens. The product preserves unavailable
              signal lanes rather than filling gaps with a made-up conclusion.
            </p>
          </div>
          <span className="rounded-chip border border-line bg-elevated/50 px-3 py-1.5 text-xs text-ink-faint">
            7 defined divisions
          </span>
        </div>
        <div className="mt-12 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {ALL_AGENTS.map((id) => {
            const analyst = AGENTS[id];
            const brief = ANALYST_BRIEFS[id];
            return (
              <article
                key={id}
                className="group relative min-h-56 overflow-hidden rounded-panel border border-line bg-surface/45 p-5 shadow-[0_18px_50px_-34px_rgb(0_0_0/0.9)] transition-[transform,border-color,background-color] duration-200 hover:-translate-y-0.5 hover:border-line-bright hover:bg-elevated/65"
              >
                <div className="flex items-start justify-between gap-4">
                  <span
                    className="flex size-12 shrink-0 items-center justify-center rounded-full border bg-abyss/70"
                    style={{ borderColor: `color-mix(in oklch, ${analyst.hue} 42%, transparent)`, color: analyst.hue }}
                  >
                    <AgentSigil agent={id} size={28} />
                  </span>
                  <span className="text-right text-[0.625rem] uppercase tracking-[0.15em] text-ink-faint">
                    {brief.status}
                  </span>
                </div>
                <h3 className="mt-7 text-xl font-medium tracking-tight text-ink">{analyst.name}</h3>
                <p className="mt-1 text-xs font-medium uppercase tracking-[0.1em] text-ink-dim">
                  {brief.signals}
                </p>
                <p className="mt-4 text-sm leading-6 text-ink-faint">{brief.detail}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="border-y border-line/70 bg-[#050918]">
        <div className="mx-auto grid max-w-[1120px] gap-8 px-6 py-24 md:grid-cols-[0.8fr_1.2fr] md:py-28">
          <div className="self-start md:sticky md:top-24">
            <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">Live intelligence</p>
            <h2 className="mt-5 text-3xl font-medium tracking-[-0.04em] text-ink sm:text-4xl">
              The Radar never stops watching.
            </h2>
            <p className="mt-5 text-base leading-7 text-ink-dim">
              Fresh detections, market observations, score reasons, and opportunity history
              stay connected so candidates can surface without manually searching the noise.
            </p>
            <Link
              href="/command"
              className="mt-8 inline-flex h-11 items-center rounded-chip bg-plasma px-5 text-sm font-medium text-void shadow-[0_8px_32px_-8px_color-mix(in_oklch,var(--color-plasma)_70%,transparent)] transition-[transform,filter] duration-150 hover:brightness-110 active:scale-[0.98]"
            >
              Open Radar
            </Link>
          </div>
          <div className="rounded-panel border border-line bg-surface/60 p-5 sm:p-6">
            <div className="flex items-center justify-between gap-4 border-b border-line pb-4">
              <div>
                <p className="text-label text-plasma">Fresh detected tokens</p>
                <p className="mt-1 text-sm text-ink-faint">A representation of the existing live Radar workflow.</p>
              </div>
              <span className="flex items-center gap-2 text-xs text-ink-dim"><i className="size-1.5 rounded-full bg-safe" /> Live path</span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {["Detection time", "Token identity", "Market observation", "Radar score", "Risk / execution context", "Opportunity history"].map((field, index) => (
                <div key={field} className="rounded-card border border-line/70 bg-abyss/55 p-3">
                  <p className="text-[0.625rem] font-medium uppercase tracking-[0.14em] text-ink-faint">{String(index + 1).padStart(2, "0")}</p>
                  <p className="mt-3 text-sm font-medium text-ink">{field}</p>
                  <div className="mt-3 h-px w-2/3 bg-line" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1120px] px-6 py-24 md:py-32">
        <div className="rounded-panel border border-line bg-surface/45 p-7 sm:p-10">
          <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">Simulation before capital</p>
          <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_0.9fr] lg:items-end">
            <div>
              <h2 className="text-3xl font-medium tracking-[-0.04em] text-ink sm:text-4xl">
                Test the strategy before the capital.
              </h2>
              <p className="mt-5 max-w-2xl text-base leading-7 text-ink-dim">
                Paper Wallet tracks simulated entries and exits against stored market observations.
                Strategy Intelligence keeps the resulting evidence visible before any real-capital
                decision is considered.
              </p>
            </div>
            <p className="border-l border-line pl-5 text-sm leading-6 text-ink-faint">
              Paper Wallet is a simulation. Its record includes modeled execution costs and does
              not promise future performance.
            </p>
          </div>
        </div>
      </section>

      <section className="border-y border-line/70 bg-surface/[0.2]">
        <div className="mx-auto grid max-w-[1120px] gap-10 px-6 py-24 md:grid-cols-[1fr_0.9fr] md:py-28">
          <div>
            <p className="text-label font-medium uppercase tracking-[0.18em] text-plasma">Safety first. Execution later.</p>
            <h2 className="mt-5 text-3xl font-medium tracking-[-0.04em] text-ink sm:text-4xl">
              Opportunity without blind risk.
            </h2>
            <p className="mt-5 max-w-2xl text-base leading-7 text-ink-dim">
              A Radar appearance is not a safety approval. The real-wallet safety foundation
              records fail-closed checks before any future real execution could be considered.
            </p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {["Provenance and market freshness", "Buy and sell route availability", "Quote price impact and deviation", "Round-trip loss and liquidity exposure", "Mint and freeze authority checks", "Token-2022 extension allowlist"].map((check) => (
              <li key={check} className="rounded-card border border-line bg-abyss/60 px-4 py-3 text-sm text-ink-dim">
                {check}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto max-w-[1120px] px-6 py-24 md:py-32">
        <p className="max-w-4xl text-4xl font-medium tracking-[-0.055em] text-ink sm:text-5xl md:text-6xl">
          Don’t chase every token. Understand which ones deserve attention.
        </p>
        <p className="mt-6 max-w-xl text-base leading-7 text-ink-dim">
          Speed finds tokens. Intelligence decides what deserves attention.
        </p>
        <div className="mt-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PRODUCT_LINKS.map((item) => (
            <Link key={item.href} href={item.href} className="group rounded-panel border border-line bg-surface/40 p-5 transition-[transform,border-color,background-color] duration-200 hover:-translate-y-0.5 hover:border-plasma/45 hover:bg-elevated/60">
              <p className="text-base font-medium text-ink">{item.title}</p>
              <p className="mt-2 text-sm leading-6 text-ink-faint">{item.body}</p>
              <span className="mt-6 inline-block text-sm text-plasma transition-transform duration-150 group-hover:translate-x-0.5">Open →</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
