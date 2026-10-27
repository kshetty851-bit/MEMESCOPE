"use client";

/**
 * USER 1's real trades beside the Pump Catcher Lab (Karthik, 2026-10-27: "so i
 * can check from mobile or other laptop"). Read only; the wallet itself stays
 * in the device-locked JUPITER box on /real-wallet.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Trade { mint: string; symbol: string | null; opened_at: string; closed_at: string | null; open: boolean;
  stake_usd: number | null; pnl_usd: number | null; pct: number | null; how: string | null; lab_pct: number | null }
interface User1 { since: string; balance_usd: string | null; balance_sol: string | null; balance_error: string | null;
  trades: number; open: number; wins: number; pnl_usd: number; lab_pnl_same_coins_usd: number; trades_list: Trade[] }

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const usd = (v: number) => `${v < 0 ? "−" : "+"}$${Math.abs(v).toFixed(2)}`;
const pct = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
const tone = (v: number | null) => (v === null ? "text-ink-dim" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim");
const at = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI });

export function User1Real() {
  const { data: d, isError } = useQuery({
    queryKey: ["pump-catcher-user1"],
    queryFn: () => api.get<User1>("/labs/graduation/karthik/pump-catcher/user1"),
    refetchInterval: 30_000,
  });
  if (isError) return <p className="text-sm text-down">USER 1&apos;s trades could not be read.</p>;
  if (!d) return null;
  return (
    <section className="rounded-2xl border border-accent/40 bg-accent/[0.04] p-4" data-testid="user1-real">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">USER 1 · real money, following this lab</h2>
        <span className="text-[11px] text-ink-dim">since {at(d.since)} · updates every 30 s</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Fig label="Balance" value={d.balance_usd ? `$${Number(d.balance_usd).toFixed(2)}` : "unread"}
             sub={d.balance_sol ? `${Number(d.balance_sol).toFixed(3)} SOL` : d.balance_error ?? ""} />
        <Fig label="Profit / loss" value={usd(d.pnl_usd)} cls={tone(d.pnl_usd)} sub={`lab on the same coins ${usd(d.lab_pnl_same_coins_usd)}`} />
        <Fig label="Trades" value={String(d.trades)} sub={`${d.trades ? Math.round((100 * d.wins) / d.trades) : 0}% won`} />
        <Fig label="Open now" value={String(d.open)} sub="sells at +30%, at 5 min if down, else 10 min" />
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
            <tr>
              <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
              <th className="py-1.5 pr-3 text-left font-normal">Bought</th>
              <th className="py-1.5 pr-3 text-right font-normal">USER 1</th>
              <th className="py-1.5 pr-3 text-right font-normal">Lab</th>
              <th className="py-1.5 pr-3 text-right font-normal">P/L</th>
              <th className="py-1.5 text-left font-normal">Sold</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-subtle">
            {d.trades_list.map((t) => (
              <tr key={`${t.mint}${t.opened_at}`}>
                <td className="py-1.5 pr-3">
                  <a href={`https://dexscreener.com/solana/${t.mint}`} target="_blank" rel="noreferrer" className="font-medium text-ink hover:text-accent">
                    {cleanName(t.symbol) ?? `${t.mint.slice(0, 4)}…`}</a>
                </td>
                <td className="py-1.5 pr-3 text-ink-dim">{at(t.opened_at)}</td>
                <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${tone(t.pct)}`}>{t.open ? "open" : pct(t.pct)}</td>
                <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${tone(t.lab_pct)}`}>{t.lab_pct === null ? "—" : pct(t.lab_pct)}</td>
                <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${tone(t.pnl_usd)}`}>{t.pnl_usd === null ? "—" : usd(t.pnl_usd)}</td>
                <td className="py-1.5 text-[12px] text-ink-dim">{t.how ?? (t.open ? "holding" : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-ink-faint">“Lab” is the Pump Catcher Lab&apos;s paper result on the same coin; “—” means the lab did not buy it or has not priced it yet. Not financial advice.</p>
    </section>
  );
}

function Fig({ label, value, sub, cls = "text-ink" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className={`mt-0.5 font-mono text-lg font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}
