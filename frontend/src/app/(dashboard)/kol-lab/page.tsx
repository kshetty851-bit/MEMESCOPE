"use client";

import { LabTradesTable } from "@/components/lab/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";
import { useKolBoard, useKolTrades, useKolWallets } from "@/hooks/use-kol";
import type { KolWallet } from "@/types/kol";

/**
 * THE KOL LAB — do the wallets that were early into winners keep being early?
 *
 * This page spends its first week showing NOTHING TRADED, and that state is
 * the most important thing it renders. The tournament refuses to open until
 * the collector has produced enough history to rank on, because `valid_from`
 * can never move and a tournament opened early would permanently be a test of
 * wallets picked from an afternoon. So the waiting panel explains what it is
 * waiting for and how far along it is, rather than looking broken.
 *
 * The ranking is shown BESIDE THE BASE RATE, always. A hit rate on its own is
 * unreadable: if being early into anything doubles a third of the time, a
 * wallet at 35% is noise wearing a rosette.
 */

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

function rate(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `${(Number(v) * 100).toFixed(0)}%`;
}

function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function WalletCard({ w, starting }: { w: KolWallet; starting: number }) {
  const control = w.is_control || w.strategy_id === "KOL-02";
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
    </Panel>
  );
}

export default function KolLabPage() {
  const { data, isLoading, isError } = useKolBoard();
  const ranking = useKolWallets();
  const trades = useKolTrades();
  const starting = Number(data?.starting_equity ?? 100);
  const base = ranking.data?.base_rate ?? null;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="KOL Lab"
        title="Do the wallets that got in early keep getting in early?"
        description="Two $100 wallets differing in one condition: one only buys coins a followed wallet bought first. The followed wallets were scored on the week BEFORE this started and frozen — nothing after that touched the selection. Nothing here is real money."
      />

      <Panel density="compact">
        <Label>WHAT THIS CAN AND CANNOT SHOW</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "Research simulation. Two virtual $100 wallets differing in one condition. No real order was ever placed."}
        </p>
      </Panel>

      {/* The waiting state is the point for the first week — see the file docstring. */}
      {ranking.data && !ranking.data.frozen ? (
        <Panel density="compact">
          <Label>WAITING FOR ENOUGH HISTORY</Label>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            No wallet has been followed yet. The collector records who bought
            each coin first, and a wallet is only scored once it has been early
            into at least {ranking.data.min_early_buys} coins — a wallet with
            two lucky calls has a 100% hit rate and means nothing.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            The tournament will not open until there are enough ranked wallets
            to test. That is deliberate: its start date can never be moved
            afterwards, so opening it early would permanently make this a test
            of wallets chosen from an afternoon of data. Expect roughly a week.
          </p>
          <p className="mt-3 font-mono text-[11px] text-muted">
            scored so far{" "}
            <span className="text-ink">{ranking.data.base_rate_sample}</span>{" "}
            early buys · base rate{" "}
            <span className="text-ink">{rate(base)}</span> · a coin counts as a
            hit at {ranking.data.hit_multiple}x within{" "}
            {ranking.data.hit_horizon_hours}h
          </p>
        </Panel>
      ) : null}

      {ranking.data?.frozen ? (
        <Panel density="compact">
          <Label>THE WALLETS THIS FOLLOWS</Label>
          <p className="mt-1 text-[11px] text-muted">
            Frozen {ranking.data.computed_at?.slice(0, 16).replace("T", " ")} ·
            base rate <span className="font-mono text-ink">{rate(base)}</span>{" "}
            over {ranking.data.base_rate_sample} early buys — a score near this
            is noise, not skill
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] uppercase text-muted">
                  <th className="pb-1 pr-3 text-left font-normal">#</th>
                  <th className="pb-1 pr-3 text-left font-normal">Wallet</th>
                  <th className="pb-1 pr-3 text-right font-normal">Early buys</th>
                  <th className="pb-1 pr-3 text-right font-normal">Hits</th>
                  <th className="pb-1 text-right font-normal">Hit rate</th>
                </tr>
              </thead>
              <tbody>
                {ranking.data.wallets.map((w) => (
                  <tr key={w.wallet} className="border-t border-line">
                    <td className="py-1.5 pr-3 font-mono text-[10px] text-muted">
                      {w.rank}
                    </td>
                    <td className="break-all py-1.5 pr-3 font-mono text-[10px] text-ink">
                      {w.wallet}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-muted">
                      {w.early_buys}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-muted">
                      {w.hits}
                    </td>
                    <td
                      className={`py-1.5 text-right font-mono ${
                        base !== null && w.hit_rate > base ? "text-up" : "text-ink"
                      }`}
                    >
                      {rate(w.hit_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

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
          <Label>NOT TRADING YET</Label>
          <p className="mt-2 text-xs text-muted">
            The registry exists ({data.spec_version}) but no tournament has been
            opened, so neither wallet is trading.
          </p>
        </Panel>
      ) : (
        <>
          {/* Signal first, control second, never sorted by outcome. */}
          <div className="grid gap-4 lg:grid-cols-2">
            {data.wallets.map((w) => (
              <WalletCard key={w.strategy_id} w={w} starting={starting} />
            ))}
          </div>
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
