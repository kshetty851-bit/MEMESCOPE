"use client";

import { useMemo, useState } from "react";

import { LabTradesTable } from "@/components/lab/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";

import { useMatrixBoard, useMatrixTrades } from "@/hooks/use-matrix";
import type { MatrixWallet } from "@/types/matrix";

/**
 * THE MATRIX LAB — twenty-four wallets laid out as a grid, not a leaderboard.
 *
 * The layout is the argument. Each section is a table whose ROWS are book
 * shapes and whose COLUMNS are holding periods, so two adjacent cells differ
 * in exactly one thing and a whole row or column reads as a dose-response.
 *
 * Nothing on this page sorts, highlights or ranks by outcome. With
 * twenty-four books the single best line is very probably noise — V6 ran
 * twenty wallets here and eighteen finished below the failure floor — and a
 * board that put the leader on top would invite precisely the reading this
 * design exists to prevent. The only interaction is picking a cell to read
 * its trades.
 */

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function clockLabel(m: number | null): string {
  return m === null ? "no clock" : `${m} min`;
}

/** One cell. Deliberately the same size and weight whatever it holds. */
function Cell({
  w,
  starting,
  selected,
  onSelect,
}: {
  w: MatrixWallet | undefined;
  starting: number;
  selected: boolean;
  onSelect: () => void;
}) {
  if (!w) {
    return (
      <td className="border border-line p-2 text-center text-[10px] text-muted">—</td>
    );
  }
  return (
    <td className="border border-line p-0 align-top">
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`flex w-full flex-col gap-0.5 p-2 text-left transition-colors ${
          selected ? "bg-accent/10 ring-1 ring-inset ring-accent/40" : "hover:bg-line/30"
        }`}
      >
        <span className="font-mono text-[10px] uppercase text-muted">{w.strategy_id}</span>
        <span className={`font-mono text-base tabular-nums ${tone(w.equity, starting)}`}>
          {money(w.equity)}
        </span>
        <span className={`font-mono text-[10px] tabular-nums ${tone(w.realised_pnl, 0)}`}>
          real {money(w.realised_pnl)}
        </span>
        <span className="font-mono text-[10px] text-muted tabular-nums">
          {w.open_positions} open · {w.closed_positions} closed
        </span>
      </button>
    </td>
  );
}

function Section({
  title,
  blurb,
  wallets,
  starting,
  selected,
  onSelect,
}: {
  title: string;
  blurb: string;
  wallets: MatrixWallet[];
  starting: number;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  // Axes read off the data rather than hardcoded, so the page cannot drift
  // from the spec if an arm is added or a clock changed.
  const clocks = useMemo(() => {
    const seen = new Map<string, number | null>();
    for (const w of wallets) seen.set(String(w.clock_minutes), w.clock_minutes);
    return [...seen.values()].sort((a, b) => {
      if (a === null) return 1;
      if (b === null) return -1;
      return a - b;
    });
  }, [wallets]);

  const shapes = useMemo(() => {
    const seen: string[] = [];
    for (const w of wallets) {
      const s = w.shape ?? "—";
      if (!seen.includes(s)) seen.push(s);
    }
    return seen;
  }, [wallets]);

  const at = (shape: string, clock: number | null) =>
    wallets.find((w) => (w.shape ?? "—") === shape && w.clock_minutes === clock);

  const equity = wallets.reduce((sum, w) => sum + Number(w.equity ?? 0), 0);
  const book = starting * wallets.length;

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Label>{title}</Label>
        <span className="font-mono text-[10px] text-muted tabular-nums">
          {wallets.length} arms · {money(book)} deployed ·{" "}
          <span className={tone(equity, book)}>{money(equity)}</span> now
        </span>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-ink-3">{blurb}</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse">
          <thead>
            <tr>
              <th className="border border-line p-2 text-left text-[10px] uppercase text-muted">
                book shape
              </th>
              {clocks.map((c) => (
                <th
                  key={String(c)}
                  className="border border-line p-2 text-center text-[10px] uppercase text-muted"
                >
                  {clockLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shapes.map((shape) => (
              <tr key={shape}>
                <th className="border border-line p-2 text-left font-mono text-[11px] font-normal text-ink">
                  {shape}
                </th>
                {clocks.map((c) => {
                  const w = at(shape, c);
                  return (
                    <Cell
                      key={`${shape}-${String(c)}`}
                      w={w}
                      starting={starting}
                      selected={!!w && w.strategy_id === selected}
                      onSelect={() => w && onSelect(w.strategy_id)}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function MatrixLabPage() {
  const { data, isLoading, isError } = useMatrixBoard();
  const [selected, setSelected] = useState<string | null>(null);
  const trades = useMatrixTrades(selected ?? undefined);
  const starting = Number(data?.starting_equity ?? 100);

  const fresh = (data?.wallets ?? []).filter((w) => w.section === "FRESH");
  const aged = (data?.wallets ?? []).filter((w) => w.section === "AGED");

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Matrix Lab"
        title="Two populations, four clocks, three book shapes"
        description="Twenty-four $100 paper wallets arranged as a factorial: fresh pump.fun launches in one section, tokens at least 24 hours old in the other, each crossed with a 5, 15 or 30 minute hold or no clock at all, and with a $2 x 50, $10 x 10 or $20 x 5 book. Every arm banks at +10% and compounds from what it realised. Nothing here is real money."
      />

      {/* Above the numbers and not collapsible: with this many books the
          headline number is the easiest thing on the page to misread. */}
      <Panel density="compact">
        <Label>WHAT THIS CAN AND CANNOT SHOW</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "A grid, not a horse race. Twenty-four wallets differing one dimension at a time. No real order was ever placed."}
        </p>
      </Panel>

      {isLoading ? (
        <Panel density="compact">
          <p className="text-xs text-muted">Loading…</p>
        </Panel>
      ) : isError || !data ? (
        <Panel density="compact">
          <Label>NOT AVAILABLE</Label>
          <p className="mt-2 text-xs text-down">
            The board could not be read. This says nothing about the experiment —
            only that this page could not reach it.
          </p>
        </Panel>
      ) : !data.activated ? (
        <Panel density="compact">
          <Label>NOT ACTIVATED</Label>
          <p className="mt-2 text-xs text-muted">
            The registry exists ({data.spec_version}) but no tournament has been
            opened, so none of the arms are trading yet.
          </p>
        </Panel>
      ) : (
        <>
          <Panel density="compact">
            <Label>THE RULES BOTH SECTIONS SHARE</Label>
            <p className="mt-2 text-xs text-muted">
              Liquidity at least{" "}
              <span className="font-mono text-ink">
                {money(Number(data.min_liquidity_usd))}
              </span>{" "}
              · bank the wallet at{" "}
              <span className="font-mono text-ink">
                {data.target_multiple ?? "1.10"}x
              </span>{" "}
              and compound from what was realised · no take-profit and no stop on
              any position · every book fully deployable
            </p>
          </Panel>

          <Section
            title="FRESH — pump.fun launches"
            blurb="Drawn from the radar stream and required to carry the launchpad's own mint suffix, which is the filter that removed the impostor pairs from the Movers Lab. These coins are minutes to hours old: across 148 coins the movers labs judged, the median age at the checkpoint was 1.26 hours and the oldest 18.5."
            wallets={fresh}
            starting={starting}
            selected={selected}
            onSelect={setSelected}
          />

          <Section
            title={`AGED — established markets, at least ${data.min_age_hours ?? "24"}h old`}
            blurb="Sampled from deep Raydium, Orca, Meteora and MetaDAO markets, with the age condition enforced rather than assumed. The honest prior: a breakout entry on established tokens has already measured 2.73 percentage points WORSE than a random bar in the same tokens. This section runs to find out whether the CLOCK behaves differently here, not because the population is expected to win."
            wallets={aged}
            starting={starting}
            selected={selected}
            onSelect={setSelected}
          />

          <Panel density="compact">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Label>{selected ? `TRADES · ${selected}` : "TRADES · ALL ARMS"}</Label>
              {selected ? (
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="font-mono text-[10px] uppercase text-muted hover:text-ink"
                >
                  show all
                </button>
              ) : (
                <span className="font-mono text-[10px] text-muted">
                  pick a cell above to isolate one arm
                </span>
              )}
            </div>
          </Panel>

          {trades.data ? (
            <LabTradesTable trades={trades.data.trades} />
          ) : (
            <Panel density="compact">
              <Label>TRADES</Label>
              <p className="mt-2 text-xs text-muted">
                {trades.isError ? "The trade list could not be read." : "Loading…"}
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
