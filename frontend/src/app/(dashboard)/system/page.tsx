"use client";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { AiCore } from "@/components/brand/ai-core";
import { LogoMark, Wordmark } from "@/components/brand/logo";
import { TokenAvatar } from "@/components/brand/token-avatar";
import { AgentBadge, Badge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AnimatedNumber, Meter, Metric } from "@/components/ui/metric";
import { Label, Panel, PanelTitle } from "@/components/ui/panel";
import { Skeleton, SkeletonTokenCard } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  AGENTS,
  ALL_AGENTS,
  STATUS_LABEL,
  STATUS_TONE,
  type AgentStatus,
} from "@/lib/design/agents";
import { ModeToggle } from "@/components/layout/mode-toggle";

/**
 * DESIGN SYSTEM
 *
 * A living styleguide, not a static PDF. Every swatch, component and motion
 * sample on this page is the real thing imported from the real module — so it
 * cannot drift out of date, which is the failure mode of every brand guideline
 * ever written.
 */

function Section({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-heading font-medium text-ink">{title}</h2>
        {caption && <p className="mt-1 max-w-2xl text-sm text-ink-faint">{caption}</p>}
      </div>
      {children}
    </section>
  );
}

function Swatch({ name, token }: { name: string; token: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-16 rounded-card border border-line"
        style={{ background: `var(--color-${token})` }}
      />
      <div>
        <p className="text-xs text-ink">{name}</p>
        <p data-numeric className="text-[0.6875rem] text-ink-faint">
          --color-{token}
        </p>
      </div>
    </div>
  );
}

export default function DesignSystemPage() {
  return (
    <div className="flex max-w-5xl flex-col gap-14 pb-12">
      <header>
        <Label>Brand guidelines</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          The MEMESCOPE design system
        </h1>
        <p className="mt-3 max-w-2xl text-ink-dim">
          Signal in the void. A dark, dimensional canvas where intelligence arrives as
          light, data has mass, and everything is observed through an instrument.
        </p>
      </header>

      <Section
        title="The mark"
        caption="An aperture: a ring of segments closing on a single lit point — an instrument iris the moment it resolves a signal. It survives being 16px in a browser tab, which is the only size test that matters."
      >
        <Panel className="flex flex-wrap items-center gap-10">
          <LogoMark size={64} className="text-plasma" />
          <LogoMark size={32} className="text-plasma" />
          <LogoMark size={16} className="text-plasma" />
          <Wordmark />
        </Panel>
      </Section>

      <Section
        title="Colour"
        caption="Five substrate steps on one desaturated blue-violet — depth comes from stacking, never from shadows on flat black. Gold is reserved exclusively for APEX; using it anywhere else devalues the one thing that should feel rare."
      >
        <div>
          <Label>Substrate</Label>
          <div className="mt-3 grid grid-cols-3 gap-4 sm:grid-cols-5">
            {["void", "abyss", "surface", "elevated", "raised"].map((token) => (
              <Swatch key={token} name={token} token={token} />
            ))}
          </div>
        </div>
        <div className="mt-4">
          <Label>Brand &amp; agents</Label>
          <div className="mt-3 grid grid-cols-3 gap-4 sm:grid-cols-5">
            <Swatch name="plasma" token="plasma" />
            {ALL_AGENTS.map((id) => (
              <Swatch key={id} name={id} token={id} />
            ))}
          </div>
        </div>
      </Section>

      <Section
        title="Typography"
        caption="Geist Sans for language, Geist Mono for every figure on screen. That single rule — all numerals are mono and tabular — is the most recognisable thing about the interface."
      >
        <Panel className="flex flex-col gap-6">
          <div>
            <Label>Display · 4.5rem / -0.04em</Label>
            <p className="mt-1 text-[3rem] font-semibold leading-none tracking-[-0.04em]">
              Discover gems
            </p>
          </div>
          <div>
            <Label>Title · 2rem</Label>
            <p className="mt-1 text-title font-semibold">Command Center</p>
          </div>
          <div>
            <Label>Heading · 1.125rem</Label>
            <p className="mt-1 text-heading font-medium">Division findings</p>
          </div>
          <div>
            <Label>Body · 0.875rem</Label>
            <p className="mt-1 text-sm text-ink-dim">
              The Intelligence Division continuously scans Solana and analyses every launch.
            </p>
          </div>
          <div>
            <Label>Numeric · mono, tabular</Label>
            <p data-numeric className="mt-1 text-xl">
              $17.85M · 0.017840 · 1,317 / 138
            </p>
          </div>
        </Panel>
      </Section>

      <Section
        title="Agent sigils"
        caption="Geometric sigils, not mascots. A cartoon frog dates instantly and reads as a meme project; a sigil reads as an institution. Drawn on a 48px grid with 1.5px strokes so they hold from 12px to 200px."
      >
        <Panel className="grid grid-cols-2 gap-6 sm:grid-cols-4 lg:grid-cols-7">
          {ALL_AGENTS.map((id) => (
            <div key={id} className="flex flex-col items-center gap-2 text-center">
              <span style={{ color: AGENTS[id].hue }}>
                <AgentSigil agent={id} size={44} alive />
              </span>
              <span className="text-label uppercase" style={{ color: AGENTS[id].hue }}>
                {AGENTS[id].name}
              </span>
            </div>
          ))}
        </Panel>
      </Section>

      <Section
        title="Operational status"
        caption="Seven states, all present-tense verbs — the division is never 'done'. Only Alert breaks the specialist's own hue, because it is the one state that must interrupt."
      >
        <Panel className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {(
            [
              "monitoring",
              "analysing",
              "learning",
              "investigating",
              "alert",
              "synchronising",
              "idle",
            ] as AgentStatus[]
          ).map((status) => (
            <span
              key={status}
              className="text-[0.5625rem] uppercase tracking-[0.1em]"
              style={{ color: STATUS_TONE[status] ?? "var(--color-plasma)" }}
            >
              {STATUS_LABEL[status]}
            </span>
          ))}
        </Panel>
      </Section>

      <Section
        title="Display modes"
        caption="Observatory is the full atmosphere. Command strips every non-informational effect for professionals who keep this open all day — identical functionality, no ornament. The switch writes one attribute on the document, so it costs a single style recalculation."
      >
        <Panel className="flex flex-wrap items-center gap-6">
          <ModeToggle compact />
          <p className="text-sm text-ink-faint">
            Try it — the ambient field, panel blur and every ambient loop stop instantly.
            The Core stills but never disappears.
          </p>
        </Panel>
      </Section>

      <Section
        title="Buttons"
        caption="At most one plasma-glow primary per view. Scarcity makes the primary action read as inevitable."
      >
        <Panel className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Launch Command Center</Button>
          <Button variant="outline">Watch Live Scanner</Button>
          <Button variant="surface">Surface</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Revoke</Button>
          <Button variant="surface" loading>
            Loading
          </Button>
          <Button variant="surface" disabled>
            Disabled
          </Button>
        </Panel>
      </Section>

      <Section title="Badges & status">
        <Panel className="flex flex-wrap items-center gap-3">
          <Badge tone="neutral">Neutral</Badge>
          <Badge tone="safe">Trading</Badge>
          <Badge tone="warn">Watch</Badge>
          <Badge tone="danger">High risk</Badge>
          <Badge tone="plasma">Live</Badge>
          <Badge tone="apex">
            <AgentSigil agent="apex" size={11} />
            Elite Gem
          </Badge>
          <AgentBadge agent="oracle" />
          <AgentBadge agent="sentinel" />
          <span className="flex items-center gap-2 text-sm text-ink-dim">
            <StatusDot /> Operational
          </span>
        </Panel>
      </Section>

      <Section title="Data display">
        <div className="grid gap-4 md:grid-cols-2">
          <Panel className="flex flex-col gap-5">
            <Metric label="Market cap" value="$17.85M" size="lg" />
            <div>
              <Label>Counting numeral</Label>
              <p data-numeric className="mt-1 text-2xl">
                <AnimatedNumber value={7656} />
              </p>
            </div>
            <div>
              <Label>Confidence meter</Label>
              <Meter value={0.82} className="mt-2" />
            </div>
            <div>
              <Label>Risk meter</Label>
              <Meter value={0.68} tone="var(--color-danger)" className="mt-2" />
            </div>
          </Panel>

          <Panel className="flex flex-col gap-5">
            <div>
              <Label>Sparkline</Label>
              <Sparkline
                points={[3, 5, 4, 7, 6, 9, 8, 12, 11, 15, 14, 18]}
                width={280}
                height={64}
                tone="var(--color-safe)"
                className="mt-2"
              />
            </div>
            <div>
              <Label>Token avatars — deterministic from mint</Label>
              <div className="mt-3 flex gap-3">
                {["HHbRJ9Fw", "DezXAZ8z", "cRyAiogm", "GVP4KyY5"].map((mint) => (
                  <TokenAvatar key={mint} mint={mint} size={40} />
                ))}
              </div>
            </div>
          </Panel>
        </div>
      </Section>

      <Section
        title="Motion"
        caption="Nothing bounces. One expressive curve — a damped exponential that arrives fast and settles without overshoot. Ambient loops run 6–24s at low amplitude; if you notice them while reading, they are wrong."
      >
        <Panel className="flex flex-wrap items-center gap-10">
          <div className="flex flex-col items-center gap-3">
            <AiCore size={140} confidence={0.15} showAgents={false} />
            <span className="text-label uppercase text-ink-faint">Core · cool · 15%</span>
          </div>
          <div className="flex flex-col items-center gap-3">
            <AiCore size={140} confidence={0.95} showAgents={false} />
            <span className="text-label uppercase text-ink-faint">Core · warm · 95%</span>
          </div>
          <div className="flex flex-col items-center gap-3">
            <AiCore size={140} confidence={0.95} showAgents={false} elite />
            <span className="text-label uppercase text-ink-faint">
              Elite · one gold pulse
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <code data-numeric className="text-xs text-ink-dim">
              --ease-instrument: cubic-bezier(0.16, 1, 0.3, 1)
            </code>
            <code data-numeric className="text-xs text-ink-dim">
              --duration-quick: 200ms
            </code>
            <code data-numeric className="text-xs text-ink-dim">
              --duration-cinematic: 900ms
            </code>
          </div>
        </Panel>
      </Section>

      <Section
        title="States"
        caption="Every empty and error state is narrated by an agent. Never apologise, never blame, always say what happens next."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Panel density="flush">
            <EmptyState
              agent="apex"
              title="No Elite Gems right now"
              body="APEX certifies roughly one token in a hundred. This is the expected state most of the time."
            />
          </Panel>
          <Panel density="flush">
            <ErrorState
              body="The intelligence archive did not respond. The division is still operating."
              reference="a91f-2c"
            />
          </Panel>
          <Panel density="flush" className="md:col-span-2">
            <div className="p-4">
              <Label>Loading — skeletons mirror the shape of what is arriving</Label>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <SkeletonTokenCard />
                <div className="space-y-3">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-24 w-full" />
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </Section>

      <Section
        title="Brand voice"
        caption="Precise, never breathless. The product knows things; it does not hype them."
      >
        <Panel className="grid gap-6 sm:grid-cols-2">
          <div>
            <Label className="text-safe">We say</Label>
            <ul className="mt-2 space-y-1.5 text-sm text-ink-dim">
              <li>&ldquo;Momentum accelerating above baseline.&rdquo;</li>
              <li>&ldquo;No security concerns detected.&rdquo;</li>
              <li>&ldquo;Insufficient conviction to recommend action.&rdquo;</li>
              <li>&ldquo;Intelligence, not advice.&rdquo;</li>
            </ul>
          </div>
          <div>
            <Label className="text-danger">We never say</Label>
            <ul className="mt-2 space-y-1.5 text-sm text-ink-faint line-through decoration-danger/50">
              <li>&ldquo;🚀 100x GEM ALERT!!&rdquo;</li>
              <li>&ldquo;Guaranteed returns.&rdquo;</li>
              <li>&ldquo;Don&rsquo;t miss out — buy now.&rdquo;</li>
              <li>&ldquo;Oops! Something went wrong.&rdquo;</li>
            </ul>
          </div>
        </Panel>
      </Section>

      <Section title="Accessibility">
        <Panel className="grid gap-4 text-sm text-ink-dim sm:grid-cols-2">
          {[
            "Ink on substrate exceeds WCAG AA at every tier; ink-faint is reserved for non-essential text.",
            "prefers-reduced-motion halts every ambient loop and collapses transitions.",
            "Full keyboard traversal with a visible 2px plasma focus ring on all interactives.",
            "Meters expose role, value and label; sigils are aria-hidden with text alternatives.",
            "Desktop-first three-column layouts collapse to single column; the rail becomes a bottom bar.",
            "Status is never carried by colour alone — every state pairs hue with a label.",
          ].map((line) => (
            <p key={line} className="flex gap-2">
              <span className="text-plasma">—</span>
              {line}
            </p>
          ))}
        </Panel>
      </Section>

      <Section title="Panels">
        <div className="grid gap-4 md:grid-cols-3">
          <Panel>
            <PanelTitle className="text-sm">Comfortable</PanelTitle>
            <p className="mt-2 text-sm text-ink-faint">Default. 24px padding.</p>
          </Panel>
          <Panel density="compact" accent={AGENTS.pulse.hue}>
            <PanelTitle className="text-sm">Compact + accent</PanelTitle>
            <p className="mt-2 text-sm text-ink-faint">16px, agent top edge.</p>
          </Panel>
          <Panel density="compact" interactive className="reticle text-apex">
            <PanelTitle className="text-sm text-ink">Interactive + reticle</PanelTitle>
            <p className="mt-2 text-sm text-ink-faint">Lifts on hover.</p>
          </Panel>
        </div>
      </Section>
    </div>
  );
}
