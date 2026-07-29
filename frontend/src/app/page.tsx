import Link from "next/link";

import { AiCore } from "@/components/brand/ai-core";
import { AgentSigil } from "@/components/brand/agent-sigil";
import { Universe } from "@/components/brand/universe/universe";
import { Mascot } from "@/components/brand/mascot";
import { SpaceField } from "@/components/brand/space-field";
import { Logo } from "@/components/brand/logo";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, Label } from "@/components/ui/panel";
import { AGENTS, ALL_AGENTS, PIPELINE } from "@/lib/design/agents";
import { AUTH_BYPASS } from "@/lib/env";

export const metadata = {
  title: "LETZMOON — AI Opportunity Intelligence",
  description:
    "The Intelligence Division continuously scans Solana, analyses every launch and discovers opportunities before the market reacts.",
};

/**
 * Landing page.
 *
 * One idea per viewport, each earning the scroll to the next: the Core (what
 * it is), the Squad (who does the work), the pipeline (how a verdict is
 * reached), the entry point. No feature grid, no logo wall, no pricing table —
 * this page has to feel like a first contact, not a brochure.
 */
export default function LandingPage() {
  return (
    <div className="relative overflow-x-hidden">
      <SpaceField />
      <Universe />

      {/* --- Chrome ------------------------------------------------------- */}
      <header className="fixed inset-x-0 top-0 z-50 border-b border-line/60 bg-void/60 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Logo />
          {/* With the auth bypass active there is no session to establish, so
              offering "Sign in" would be a control that silently bounces the
              visitor to /command - the product claiming a step it does not
              take. Show the destination instead. Both branches are real; the
              flag decides which one is true. */}
          {AUTH_BYPASS ? (
            <Link href="/command">
              <Button variant="surface" size="sm">
                Enter Mission Control
              </Button>
            </Link>
          ) : (
            <div className="flex items-center gap-2">
              <Link href="/login">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/register">
                <Button variant="surface" size="sm">
                  Request access
                </Button>
              </Link>
            </div>
          )}
        </div>
      </header>

      {/* --- Hero --------------------------------------------------------- */}
      <section className="relative flex min-h-screen items-center justify-center px-6 pt-16">
        {/* The Core sits behind the headline, not beside it. The words are
            read through the instrument. */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          {/* Agent nodes are off here on purpose: at hero scale they land on
              top of the headline and read as accident rather than composition.
              The Core is atmosphere; the sigil row below carries the division. */}
          <AiCore
            size={760}
            confidence={0.78}
            showAgents={false}
            className="max-w-[95vw] opacity-60"
            label="The LETZMOON AI Core"
          />
        </div>

        {/* The mascot is the first thing to arrive and the only thing moving
            at rest. It sits behind the headline on wide screens so the words
            stay the subject; below `lg` it is hidden rather than shrunk,
            because at phone width it would either crowd the copy or be too
            small to read as a character at all. */}
        <div className="pointer-events-none absolute inset-0 hidden items-center justify-end pr-[6vw] lg:flex">
          <Mascot size={340} priority className="opacity-95" />
        </div>

        <div className="relative z-10 flex max-w-3xl flex-col items-center text-center">
          <Badge
            tone="plasma"
            className="mb-8 animate-[rise_0.6s_var(--ease-instrument)_both]"
          >
            <StatusDot tone="var(--color-plasma)" />
            Live on Solana mainnet
          </Badge>

          <h1 className="text-balance text-[clamp(2.5rem,7vw,4.5rem)] font-semibold leading-[0.98] tracking-[-0.04em] text-ink animate-[rise_0.7s_var(--ease-instrument)_0.1s_both]">
            LETZMOON{" "}
            <span className="block bg-gradient-to-r from-brand via-brand-accent to-brand-secondary bg-clip-text text-transparent">
              AI Opportunity Intelligence
            </span>
          </h1>

          <p className="mt-7 max-w-xl text-pretty text-[1.0625rem] leading-relaxed text-ink-dim animate-[rise_0.7s_var(--ease-instrument)_0.2s_both]">
            Helping you discover high-quality crypto opportunities through
            explainable market intelligence.
          </p>

          <div className="mt-10 flex flex-col gap-3 sm:flex-row animate-[rise_0.7s_var(--ease-instrument)_0.3s_both]">
            <Link href="/command">
              <Button variant="primary" size="lg" className="w-full sm:w-auto">
                Enter Mission Control
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="size-4"
                >
                  <path
                    d="M5 12h14M13 6l6 6-6 6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </Button>
            </Link>
            <Link href="/radar">
              <Button variant="outline" size="lg" className="w-full sm:w-auto">
                Explore Radar
              </Button>
            </Link>
          </div>

          {/* Signature statement. Sits below the actions, quiet enough to be
              found rather than announced — a line you notice on the second
              read, which is what makes it stick. */}
          <p className="mt-12 text-label uppercase text-ink-faint animate-[rise_0.7s_var(--ease-instrument)_0.45s_both]">
            The blockchain never sleeps. <span className="text-plasma">Neither do we.</span>
          </p>

          <div className="mt-10 flex items-center gap-6 text-ink-faint animate-[rise_0.7s_var(--ease-instrument)_0.55s_both]">
            {ALL_AGENTS.map((id) => (
              <span key={id} style={{ color: AGENTS[id].hue }} title={AGENTS[id].name}>
                <AgentSigil
                  agent={id}
                  size={22}
                  className="opacity-70 transition-opacity hover:opacity-100"
                />
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* --- The Squad ---------------------------------------------------- */}
      <section className="relative mx-auto max-w-6xl px-6 py-32">
        <div className="mb-14 max-w-2xl">
          <Label>The Intelligence Division</Label>
          <h2 className="mt-3 text-title font-semibold text-ink">
            Seven specialists. One verdict.
          </h2>
          <p className="mt-4 text-ink-dim">
            LETZMOON is not a dashboard with alerts bolted on. It is an organisation of AI
            specialists, each with a single job, feeding one shared intelligence core.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ALL_AGENTS.map((id) => {
            const spec = AGENTS[id];
            return (
              <Panel
                key={id}
                accent={spec.hue}
                interactive
                className="group"
                density="compact"
              >
                <div className="flex items-start gap-4">
                  <div
                    className="flex size-11 shrink-0 items-center justify-center rounded-card border transition-transform duration-300 ease-[var(--ease-instrument)] group-hover:scale-110"
                    style={{
                      color: spec.hue,
                      borderColor: `color-mix(in oklch, ${spec.hue} 30%, transparent)`,
                      background: `color-mix(in oklch, ${spec.hue} 9%, transparent)`,
                    }}
                  >
                    <AgentSigil agent={id} size={24} alive />
                  </div>
                  <div className="min-w-0">
                    <p
                      className="text-sm font-semibold tracking-[0.12em]"
                      style={{ color: spec.hue }}
                    >
                      {spec.name}
                    </p>
                    <p className="mt-1 text-sm text-ink-dim">{spec.mission}</p>
                    <p className="mt-3 text-xs text-ink-faint">{spec.traits.join(" · ")}</p>
                  </div>
                </div>
              </Panel>
            );
          })}
        </div>
      </section>

      {/* --- The pipeline ------------------------------------------------- */}
      <section className="relative mx-auto max-w-4xl px-6 py-24">
        <div className="mb-12 text-center">
          <Label>Intelligence pipeline</Label>
          <h2 className="mt-3 text-title font-semibold text-ink">
            Every token runs the gauntlet.
          </h2>
        </div>

        <Panel className="overflow-visible">
          <ol className="flex flex-col gap-0 sm:flex-row sm:items-stretch">
            {PIPELINE.map((id, index) => {
              const spec = AGENTS[id];
              return (
                <li
                  key={id}
                  className="relative flex flex-1 items-center gap-3 py-3 sm:flex-col sm:gap-3 sm:py-0 sm:text-center"
                >
                  <div
                    className="ambient flex size-10 shrink-0 items-center justify-center rounded-full border animate-[breathe_6s_ease-in-out_infinite]"
                    style={{
                      color: spec.hue,
                      borderColor: `color-mix(in oklch, ${spec.hue} 35%, transparent)`,
                      background: `color-mix(in oklch, ${spec.hue} 10%, transparent)`,
                      animationDelay: `${index * 0.6}s`,
                    }}
                  >
                    <AgentSigil agent={id} size={20} />
                  </div>
                  <div className="min-w-0 sm:mt-1">
                    <p
                      className="text-label font-semibold uppercase"
                      style={{ color: spec.hue }}
                    >
                      {spec.name}
                    </p>
                    <p className="mt-1 text-xs text-ink-faint">{spec.voice}</p>
                  </div>
                  {/* Connector, desktop only */}
                  {index < PIPELINE.length - 1 && (
                    <span
                      aria-hidden
                      className="absolute left-5 top-[52px] hidden h-[calc(100%-40px)] w-px bg-line sm:left-auto sm:right-[-8px] sm:top-5 sm:block sm:h-px sm:w-4"
                    />
                  )}
                </li>
              );
            })}
          </ol>

          <div className="mt-8 flex items-center justify-center gap-3 border-t border-line pt-6">
            <AgentSigil agent="apex" size={20} className="text-apex" />
            <p className="text-sm text-ink-dim">
              Clear all six and <span className="font-medium text-apex">APEX</span>{" "}
              certifies an Elite Gem. Roughly one in a hundred.
            </p>
          </div>
        </Panel>
      </section>

      {/* --- Entry -------------------------------------------------------- */}
      <section className="relative mx-auto max-w-4xl px-6 pb-32 pt-12 text-center">
        <AiCore
          size={180}
          confidence={0.9}
          showAgents={false}
          className="mx-auto mb-8 opacity-80"
          elite
        />
        <h2 className="text-balance text-title font-semibold text-ink">
          The market reacts in minutes. You will know in seconds.
        </h2>
        <div className="mt-8 flex justify-center">
          <Link href="/command">
            <Button variant="primary" size="lg">
              Launch Command Center
            </Button>
          </Link>
        </div>
      </section>

      <footer className="border-t border-line/60 px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 sm:flex-row">
          <Logo size={18} />
          <p className="text-xs text-ink-faint">
            Intelligence, not advice. Always do your own research.
          </p>
        </div>
      </footer>
    </div>
  );
}
