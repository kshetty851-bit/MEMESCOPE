"use client";

/**
 * Small First Buy test (Karthik, 2026-11-05: "yes add it since day 1 for
 * november and revise it"). Paper only, $5 a trade, priced from the on-chain
 * first-minute recorder; folded to one line like USER 1's box.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Trade { mint: string; symbol: string | null; graduated_at: string; ret: number; pnl_usd: number;
  held_s: number; how: string; first_sol: number; pool_sol: number }
interface Day { day: string; trades: number; wins: number; rugs: number; pnl_usd: number }
export interface SmallFirst { started_at: string; priced_until: string | null; ticket_usd: number; trades: number;
  wins: number; rugs: number; pnl_usd: number; days: Day[]; recent: Trade[] }

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const usd = (v: number) => `${v < 0 ? "−" : "+"}$${Math.abs(v).toFixed(2)}`;
const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim");
const at = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI });

export function SmallFirstBox() {
  const { data: d, isError } = useQuery({
    queryKey: ["small-first"],
    queryFn: () => api.get<SmallFirst>("/labs/graduation/small-first"),
    refetchInterval: 60_000,
  });
  if (isError) return <p className="text-sm text-down">The Small First Buy test could not be read.</p>;
  if (!d) return null;
  return <SmallFirstView d={d} />;
}

export function SmallFirstView({ d }: { d: SmallFirst }) {
  return (
    <details className="group rounded-2xl border border-line bg-sunken/40 px-4 py-3" data-testid="small-first">
      <summary className="flex cursor-pointer select-none flex-wrap items-baseline justify-between gap-3 [&::-webkit-details-marker]:hidden">
        <h2 className="text-base font-semibold text-ink">
          <span className="mr-1.5 inline-block text-ink-dim transition-transform group-open:rotate-90">›</span>
          Small First Buy test · paper
        </h2>
        <span className="text-[12px] text-ink-dim tabular-nums">
          <span className={tone(d.pnl_usd)}>{usd(d.pnl_usd)}</span> · {d.trades} trades at ${d.ticket_usd} · tap to open
        </span>
      </summary>
      <p className="mt-2 text-[13px] text-ink-2">
        Buys a new coin 45 seconds after it graduates when the first buy was small (pool under 110 SOL at 10 seconds)
        and the name has 1–5 letters. Sells at +30% after costs, else at 5 minutes. Fees, Jupiter&apos;s cut and 0.5%
        slippage each way are counted. Found by a search on 28 Oct–4 Nov, so only days from 5 Nov on are a fair test.
      </p>
      <div className="mt-1 text-[11px] text-ink-dim">
        since {at(d.started_at)}{d.priced_until ? ` · priced up to ${at(d.priced_until)}` : " · pricing…"} ·{" "}
        {d.trades ? Math.round((100 * d.wins) / d.trades) : 0}% won · {d.rugs} rugs (lost half or more)
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[24rem] text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
            <tr>
              <th className="py-1.5 pr-3 text-left font-normal">Day</th>
              <th className="py-1.5 pr-3 text-right font-normal">Trades</th>
              <th className="py-1.5 pr-3 text-right font-normal">Won</th>
              <th className="py-1.5 pr-3 text-right font-normal">Rugs</th>
              <th className="py-1.5 text-right font-normal">P/L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-subtle" data-testid="small-first-days">
            {d.days.map((x) => (
              <tr key={x.day}>
                <td className="py-1.5 pr-3 text-ink-dim">
                  {new Date(`${x.day}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{x.trades}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{x.wins}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{x.rugs}</td>
                <td className={`py-1.5 text-right font-mono tabular-nums ${tone(x.pnl_usd)}`}>{usd(x.pnl_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.recent.length ? (
        <div className="mt-3 overflow-x-auto">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">Latest trades</div>
          <table className="mt-1 w-full min-w-[28rem] text-sm">
            <tbody className="divide-y divide-line-subtle">
              {d.recent.map((t) => (
                <tr key={t.mint}>
                  <td className="py-1.5 pr-3">
                    <a href={`https://dexscreener.com/solana/${t.mint}`} target="_blank" rel="noreferrer" className="font-medium text-ink hover:text-accent">
                      {cleanName(t.symbol) ?? `${t.mint.slice(0, 4)}…`}</a>
                  </td>
                  <td className="py-1.5 pr-3 text-ink-dim">{at(t.graduated_at)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-ink-dim">{Math.round(t.pool_sol)} SOL</td>
                  <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${tone(t.ret)}`}>{`${t.ret > 0 ? "+" : ""}${(100 * t.ret).toFixed(1)}%`}</td>
                  <td className="py-1.5 text-[12px] text-ink-dim">{t.how === "target" ? "+30%" : "5 min"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="mt-2 text-[11px] text-ink-faint">Paper only — nothing real trades on this. Not financial advice.</p>
    </details>
  );
}
