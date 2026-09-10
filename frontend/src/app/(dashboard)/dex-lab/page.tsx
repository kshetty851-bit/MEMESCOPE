"use client";

import { useEffect, useState } from "react";

import { LabTradesTable } from "@/components/lab/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";

import { useDexBoard, useDexTrades } from "@/hooks/use-dex";
import type { DexWallet } from "@/types/dex";

/**
 * THE DEX LAB — is a DexScreener top gainer visible before it is one?
 *
 * Two $100 wallets differing in exactly one condition. The layout puts them
 * SIDE BY SIDE and never ranks them: the comparison is the finding, and a page
 * that sorted by equity would let a reader take today's position for a result.
 *
 * The disclosure sits above the numbers and is not collapsible. The
 * measurement behind this lab is the most favourable one this platform has
 * produced and therefore the easiest to overstate: it comes from a single
 * three-day window, a fifth of the signal arm's positions went to zero, and
 * the first cut of the same study read 1.7x purely because the tokens that
 * died had dropped out of the sample.
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

/** How long this tournament has been running, ticking live.
 *
 *  Rendered only after mount and from a state clock rather than `Date.now()`
 *  during render: the server would otherwise produce one elapsed time, the
 *  client another a moment later, and React would report a hydration mismatch
 *  on a value that is correct in both.
 */
function RunningFor({ since }: { since: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (now === null) return null;
  const started = Date.parse(since);
  if (!Number.isFinite(started)) return null;

  const secs = Math.max(0, Math.floor((now - started) / 1000));
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s_ = secs % 60;
  const pad = (n: number) => String(n).padStart(2, "0");

  return (
    <span className="font-mono text-ink" title={`Started ${since}`}>
      {d > 0 ? `${d}d ` : ""}
      {pad(h)}:{pad(m)}:{pad(s_)}
    </span>
  );
}

function WalletCard({ w, starting }: { w: DexWallet; starting: number }) {
  const control = w.strategy_id === "DEX-02";
  return (
    <Panel density="compact">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{w.name}</Label>
        <span
          className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase ${
            control
              ? "border-line-control text-ink-3"
              : "border-accent/40 bg-accent/10 text-accent"
          }`}
        >
          {control ? "Control" : "Signal"}
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase text-muted">Equity</div>
          <div className={`font-mono text-lg ${tone(w.equity, starting)}`}>
            {money(w.equity)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Realised</div>
          <div className={`font-mono text-lg ${tone(w.realised_pnl, 0)}`}>
            {money(w.realised_pnl)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Open</div>
          <div className="font-mono text-lg text-ink">{w.open_positions}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Closed</div>
          <div className="font-mono text-lg text-ink">{w.closed_positions}</div>
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-ink-3">{w.hypothesis}</p>

      {w.entry_text.length > 0 ? (
        <ul className="mt-2 space-y-0.5">
          {w.entry_text.map((line) => (
            <li key={line} className="font-mono text-[10px] text-muted">
              · {line}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/** The measurement, in the shape a reader can argue with.
 *
 *  Hardcoded rather than served: these are facts about a study that has already
 *  been run and frozen, not settings the engine reads. Serving them would imply
 *  they could change, and if the study is ever redone the version moves.
 */
function WhatWasMeasured() {
  return (
    <Panel density="compact">
      <Label>WHAT WAS MEASURED, AND WHAT IT DOES NOT SHOW</Label>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <div>
          <div className="text-[10px] uppercase text-muted">
            66 hours, 2026-08-21 to 08-23, liquidity ≥ $100k
          </div>
          <table className="mt-1 w-full font-mono text-[11px]">
            <thead>
              <tr className="text-muted">
                <th className="text-left font-normal">arm</th>
                <th className="text-right font-normal">n</th>
                <th className="text-right font-normal">mean</th>
                <th className="text-right font-normal">med</th>
                <th className="text-right font-normal">dead</th>
              </tr>
            </thead>
            <tbody>
              <tr className="text-accent">
                <td className="text-left">turnover ≥ 2</td>
                <td className="text-right">251</td>
                <td className="text-right">1.47x</td>
                <td className="text-right">1.22x</td>
                <td className="text-right">19.9%</td>
              </tr>
              <tr className="text-ink-3">
                <td className="text-left">control</td>
                <td className="text-right">417</td>
                <td className="text-right">0.82x</td>
                <td className="text-right">1.00x</td>
                <td className="text-right">1.9%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul className="space-y-1 text-[11px] leading-relaxed text-ink-3">
          <li>
            · One window, one regime. Split-half by time and by token both hold,
            but a split inside one window is not a different market.
          </li>
          <li>
            · A fifth of the signal arm&apos;s positions went to zero. The first
            cut of this study reported 1.7x only because those had dropped out
            of the sample.
          </li>
          <li>
            · No execution cost is in those figures, and the rule fires on
            tokens trading twenty times their liquidity in an hour — which is
            where a quoted mid and a real fill diverge most.
          </li>
          <li>
            · Nine no-edge findings precede this one. The prior is that the
            control wins.
          </li>
        </ul>
      </div>
    </Panel>
  );
}

export default function DexLabPage() {
  const { data, isLoading, isError } = useDexBoard();
  const trades = useDexTrades();
  const starting = Number(data?.starting_equity ?? 100);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Dex Lab"
        title="Can a top gainer be caught before it is one?"
        description="DexScreener's gainers board is a rear-view mirror and its API does not expose the board at all, so this rebuilds the board's input from our own price and volume record. Two $100 wallets started together over the same pool of Solana tokens with at least $100,000 of liquidity, $5 a position and twenty at once, each held six hours with no take-profit, no stop and no wallet ratchet. They differ in one condition: one only buys a token that traded at least twice its own liquidity in the previous hour. Nothing is real money."
      />

      {/* Above the numbers, and deliberately not collapsible. */}
      <Panel density="compact">
        <Label>WHAT THIS CAN AND CANNOT SHOW</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "Research simulation. Two virtual $100 wallets differing in one condition. No real order was ever placed."}
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
            opened, so neither wallet is trading yet.
          </p>
        </Panel>
      ) : (
        <>
          <Panel density="compact">
            <Label>THE RULE</Label>
            <p className="mt-2 text-xs text-muted">
              1-hour volume ÷ liquidity at least{" "}
              <span className="font-mono text-ink">
                {data.turnover_floor ?? 2}
              </span>{" "}
              (signal arm) · liquidity at least{" "}
              <span className="font-mono text-ink">
                {money(data.min_liquidity_usd)}
              </span>{" "}
              · hold{" "}
              <span className="font-mono text-ink">{data.hold_hours ?? 6}h</span>{" "}
              · no take-profit, no stop, no wallet ratchet
              {data.valid_from ? (
                <>
                  {" "}
                  · running for <RunningFor since={data.valid_from} />
                </>
              ) : null}
            </p>
          </Panel>

          {/* Side by side, ordered signal then control by the server. Never by
              equity — see the module docstring. */}
          <div className="grid gap-4 lg:grid-cols-2">
            {data.wallets.map((w) => (
              <WalletCard key={w.strategy_id} w={w} starting={starting} />
            ))}
          </div>

          <WhatWasMeasured />

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
