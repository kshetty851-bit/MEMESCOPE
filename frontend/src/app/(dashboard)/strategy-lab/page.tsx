"use client";

import { useState } from "react";

import { Experiments, RugAnalysis, TokenCompare } from "@/components/strategy-lab/analysis";
import { StrategyDiscovery } from "@/components/strategy-lab/discovery";
import { Leaderboard } from "@/components/strategy-lab/leaderboard";
import { SectionNote, SimulatedBadge, StatTile } from "@/components/strategy-lab/shared";
import { StrategyDetail } from "@/components/strategy-lab/strategy-detail";
import { StrategyGrid } from "@/components/strategy-lab/strategies";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { useLabOverview, useLabStatus } from "@/hooks/use-strategy-lab";
import { pct, type LabMode, type LabWindow } from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

/**
 * STRATEGY LAB
 *
 * Research infrastructure. Many strategy definitions replayed against ONE
 * canonical stream of token opportunities, so they can be compared on identical
 * evidence rather than on whichever tokens each happened to see.
 *
 * **This is not a wallet.** It opens no paper position, holds no lineage, signs
 * nothing, and has no state in which it could. Every balance on this page is
 * simulated research capital and is marked as such wherever it appears — not
 * as a disclaimer, but because a research surface that could be mistaken for a
 * balance is a dangerous surface.
 *
 * The page is built to report **failure** prominently. A lab that could only
 * show winners would be marketing; the point of building one is to find out
 * whether sophisticated exit logic beats doing nothing, and "it did not" is the
 * most valuable answer it can give.
 */

type Section =
  | "overview"
  | "leaderboard"
  | "strategies"
  | "compare"
  | "rugs"
  | "experiments"
  | "discovery";

const SECTIONS: { value: Section; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "leaderboard", label: "Leaderboard" },
  { value: "strategies", label: "Strategies" },
  { value: "compare", label: "Token compare" },
  { value: "rugs", label: "Rug analysis" },
  { value: "experiments", label: "Experiments" },
  { value: "discovery", label: "Discovery" },
];

function ModeSwitch({
  mode,
  onChange,
  forwardActive,
}: {
  mode: LabMode;
  onChange: (mode: LabMode) => void;
  forwardActive: boolean;
}) {
  return (
    <div
      role="group"
      aria-label="Research mode"
      className="flex gap-1 rounded-md border border-line bg-raised/50 p-1"
    >
      {(["BACKTEST", "FORWARD_RESEARCH"] as LabMode[]).map((value) => (
        <button
          key={value}
          type="button"
          onClick={() => onChange(value)}
          aria-pressed={value === mode}
          className={cn(
            "rounded-sm px-3 py-1 text-label font-medium transition-colors",
            value === mode ? "bg-surface text-ink shadow-e1" : "text-ink-3 hover:text-ink",
          )}
        >
          {value === "BACKTEST" ? "Historical replay" : "Forward research"}
          {value === "FORWARD_RESEARCH" && forwardActive ? (
            <span
              aria-hidden
              className="ml-1.5 inline-block size-1.5 rounded-full bg-up align-middle"
            />
          ) : null}
        </button>
      ))}
    </div>
  );
}

export default function StrategyLabPage() {
  const [section, setSection] = useState<Section>("overview");
  const [mode, setMode] = useState<LabMode>("BACKTEST");
  const [window, setWindow] = useState<LabWindow>("ALL");
  const [selected, setSelected] = useState<string | null>(null);

  const overview = useLabOverview(mode);
  const status = useLabStatus();
  const data = overview.data;

  const openStrategy = (id: string) => {
    setSelected(id);
    setSection("strategies");
  };

  return (
    <div className="space-y-5 pb-16">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink">STRATEGY LAB</h1>
            <p className="mt-0.5 text-sm font-medium uppercase tracking-wide text-warn">
              Research Only — No Capital Execution
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SimulatedBadge />
            <ModeSwitch
              mode={mode}
              onChange={setMode}
              forwardActive={Boolean(status.data?.forward_research_active)}
            />
          </div>
        </div>

        <p className="max-w-3xl text-sm leading-relaxed text-ink-3">
          {data?.simulated_capital_notice ??
            "Every balance shown in Strategy Lab is simulated research capital."}
        </p>

        <div className="flex flex-wrap items-center gap-3 text-xs text-ink-4">
          <span>
            State{" "}
            <span
              className={cn(
                "font-mono font-semibold",
                status.data?.state === "FORWARD_RESEARCH" ? "text-up" : "text-ink-2",
              )}
            >
              {status.data?.state ?? "…"}
            </span>
          </span>
          <span>
            Live execution path{" "}
            <span className="font-mono font-semibold text-up">
              {status.data?.live_execution_path ?? "NONE"}
            </span>
          </span>
          <span>
            Signer{" "}
            <span className="font-mono font-semibold text-up">
              {status.data?.signer ?? "NONE"}
            </span>
          </span>
          {status.data?.forward_research_active ? (
            <span>
              Forward wallets{" "}
              <span className="font-mono text-ink-2">{status.data.forward_wallets}</span> ·
              positions{" "}
              <span className="font-mono text-ink-2">{status.data.forward_positions}</span>
            </span>
          ) : null}
        </div>
      </header>

      <Tabs
        aria-label="Strategy Lab sections"
        value={section}
        onChange={(value) => {
          setSection(value);
          if (value !== "strategies") setSelected(null);
        }}
        items={SECTIONS}
      />

      {section === "overview" ? (
        overview.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Tokens evaluated"
                value={(data?.tokens_evaluated ?? 0).toLocaleString("en-US")}
                hint="canonical opportunities frozen"
              />
              <StatTile
                label="Strategies running"
                value={String(data?.strategies_running ?? 0)}
                hint="10 hypotheses + 2 benchmarks"
              />
              <StatTile
                label="Simulated trades"
                value={(data?.simulated_trades ?? 0).toLocaleString("en-US")}
                hint="no real or paper order exists"
              />
              <StatTile
                label="Forward research"
                value={data?.forward_research_active ? "ACTIVE" : "INACTIVE"}
                tone={data?.forward_research_active ? "positive" : undefined}
              />
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {(
                [
                  ["Best 7D", data?.best_7d],
                  ["Best 30D", data?.best_30d],
                  ["Lowest drawdown", data?.lowest_drawdown],
                  ["Highest moonshot capture", data?.highest_moonshot_capture],
                ] as const
              ).map(([label, headline]) => (
                <StatTile
                  key={label}
                  label={label}
                  value={headline ? headline.strategy_id : "—"}
                  tone={
                    headline
                      ? headline.wallet_return_pct >= 0
                        ? "positive"
                        : "negative"
                      : undefined
                  }
                  hint={
                    headline
                      ? `N=${headline.n} · ${pct(headline.wallet_return_pct)} · DD ${headline.max_drawdown_pct.toFixed(0)}%${headline.flags[0] ? ` · ${headline.flags[0].replaceAll("_", " ")}` : ""}`
                      : "no results yet"
                  }
                />
              ))}
            </div>

            {data ? (
              <div className="grid gap-2 lg:grid-cols-2">
                <SectionNote>{data.execution_model.disclosure}</SectionNote>
                <SectionNote>{data.execution_model.multi_target_policy_text}</SectionNote>
              </div>
            ) : null}

            <Panel density="compact">
              <p className="text-sm leading-relaxed text-ink-3">
                Strategy Lab replays every strategy against the{" "}
                <strong className="text-ink-2">same</strong> canonical opportunity
                stream — the first moment each token became eligible, frozen with
                the evidence available at that instant. Nothing here promotes a
                strategy, and ranking first is not a reason to trade one.
              </p>
            </Panel>
          </div>
        )
      ) : null}

      {section === "leaderboard" ? (
        <Leaderboard
          mode={mode}
          window={window}
          onWindowChange={setWindow}
          onSelect={openStrategy}
        />
      ) : null}

      {section === "strategies" ? (
        selected ? (
          <StrategyDetail
            strategyId={selected}
            mode={mode}
            onClose={() => setSelected(null)}
          />
        ) : (
          <StrategyGrid mode={mode} onSelect={setSelected} />
        )
      ) : null}

      {section === "compare" ? <TokenCompare mode={mode} /> : null}
      {section === "rugs" ? <RugAnalysis mode={mode} /> : null}
      {section === "experiments" ? <Experiments mode={mode} /> : null}
      {section === "discovery" ? <StrategyDiscovery /> : null}
    </div>
  );
}
