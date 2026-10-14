"use client";

/**
 * Partners Wallet (Karthik, 2026-10-14: "i want that P&L in lab section and
 * keep updating and mention on each token which startegy was used"). The main
 * real wallet from Karthik and Rafiq's 50-50 start (28 Sep, 15:00 Dubai): each
 * day's profit and % of the balance it opened with, every trade with the
 * strategy that bought it, and each strategy's totals. Real money, closed
 * trades only; SOL's own price moves are not counted, as in the box on the
 * real-wallet page.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { api } from "@/lib/api-client";

interface Day { n: number; from: string; to: string; running: boolean; trades: number; pnl_usd: string; pct: string; balance_usd: string }
interface Partner { name: string; put_in_usd: string; profit_usd: string; now_usd: string }
interface Strategy { id: string; name: string | null; pool_floor_usd: number | null; trades: number; wins: number; pnl_usd: string; first_at: string; last_at: string }
export interface PartnerTrade {
  id: string; mint_address: string; symbol: string | null; status: string; strategy_id: string | null;
  cost_usd: string | null; realised_net_pnl_usd: string | null; realised_gross_pnl_usd: string | null;
  exit_reason: string | null; opened_at: string; closed_at: string | null;
}
export interface PartnersBook {
  partners: { started_at: string; capital_usd: string; profit_usd: string; balance_usd: string; pct: string;
              trades: number; wins: number; open: number; partners: Partner[]; days: Day[] };
  strategies: Strategy[];
  trades: PartnerTrade[];
}

/** Plain words for the strategies this wallet has run. */
const PLAIN: Record<string, string> = {
  "G-QUIET": "Quiet pools $75k+, sold at 5 min",
  "G-Q50": "Quiet pools $50k+ ($50k book), sold at 5 min",
};
export const plain = (s: { id: string; name?: string | null }) => PLAIN[s.id] ?? s.name ?? s.id;

function usd(value: string | number | null | undefined, signed = false): string {
  if (value == null) return "—";
  const n = Number(value);
  const body = `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return n < 0 ? `-${body}` : signed && n > 0 ? `+${body}` : body;
}
const tone = (v: string | number) => (Number(v) > 0 ? "text-up" : Number(v) < 0 ? "text-down" : "text-ink-3");
const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const dubai = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Dubai", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const pnlOf = (t: PartnerTrade) => t.realised_net_pnl_usd ?? t.realised_gross_pnl_usd;

/** Which strategies sold coins inside a day, for its row. */
export function strategiesIn(day: Day, trades: PartnerTrade[]): string[] {
  const from = Date.parse(day.from), to = Date.parse(day.to);
  return [...new Set(trades.filter((t) => t.closed_at && Date.parse(t.closed_at) >= from && Date.parse(t.closed_at) < to)
    .map((t) => t.strategy_id ?? "?"))];
}

export function PartnersSummary({ d }: { d: PartnersBook }) {
  const p = d.partners;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="partners-summary">
      <Fig label="Balance" value={usd(p.balance_usd)} hint={`from ${usd(p.capital_usd)}`} />
      <Fig label="Profit" value={`${usd(p.profit_usd, true)} · ${pct(Number(p.pct))}`} cls={tone(p.profit_usd)} />
      <Fig label="Trades" value={String(p.trades)} hint={`${p.wins} won${p.open ? ` · ${p.open} open` : ""}`} />
      <Fig label="Each partner" value={p.partners[0] ? usd(p.partners[0].now_usd) : "—"}
           hint={p.partners.map((x) => `${x.name} ${usd(x.profit_usd, true)}`).join(" · ")} />
    </div>
  );
}

function Fig({ label, value, hint, cls = "text-ink" }: { label: string; value: string; hint?: string; cls?: string }) {
  return (
    <div className="rounded-lg border border-line p-2">
      <div className="text-[10px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div className={`mt-0.5 text-base font-semibold tabular-nums ${cls}`}>{value}</div>
      {hint ? <div className="text-[11px] tabular-nums text-ink-dim">{hint}</div> : null}
    </div>
  );
}

export function DayTable({ d }: { d: PartnersBook }) {
  return (
    <Panel>
      <PanelHeader><PanelTitle>Every day · 15:00 to 15:00 Dubai · % of the balance the day opened with</PanelTitle></PanelHeader>
      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[34rem] text-[13px] tabular-nums" data-testid="partners-days">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">day</th>
              <th className="px-2 text-right font-normal">trades</th>
              <th className="px-2 text-right font-normal">profit</th>
              <th className="px-2 text-right font-normal">%</th>
              <th className="px-2 text-right font-normal">balance</th>
              <th className="py-1 pl-3 text-left font-normal">strategy</th>
            </tr>
          </thead>
          <tbody>
            {d.partners.days.map((day) => (
              <tr key={day.n} className="border-t border-line/60">
                <td className="py-1.5 pr-3">Day {day.n} · {dubai(day.from)}{day.running ? " · so far" : ""}</td>
                <td className="px-2 text-right">{day.trades}</td>
                <td className={`px-2 text-right ${tone(day.pnl_usd)}`}>{usd(day.pnl_usd, true)}</td>
                <td className={`px-2 text-right ${tone(day.pct)}`}>{pct(Number(day.pct))}</td>
                <td className="px-2 text-right">{usd(day.balance_usd)}</td>
                <td className="py-1.5 pl-3 text-ink-3">{strategiesIn(day, d.trades).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function StrategyTable({ d }: { d: PartnersBook }) {
  return (
    <Panel>
      <PanelHeader><PanelTitle>Strategies this wallet has run</PanelTitle></PanelHeader>
      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[34rem] text-[13px] tabular-nums" data-testid="partners-strategies">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">strategy</th>
              <th className="px-2 text-left font-normal">ran</th>
              <th className="px-2 text-right font-normal">trades</th>
              <th className="px-2 text-right font-normal">won</th>
              <th className="px-2 text-right font-normal">profit</th>
            </tr>
          </thead>
          <tbody>
            {d.strategies.map((s) => (
              <tr key={s.id} className="border-t border-line/60">
                <td className="py-1.5 pr-3"><b>{s.id}</b> <span className="text-ink-3">· {plain(s)}</span></td>
                <td className="px-2 text-ink-3">{dubai(s.first_at)} → {dubai(s.last_at)}</td>
                <td className="px-2 text-right">{s.trades}</td>
                <td className="px-2 text-right">{s.trades ? `${Math.round((100 * s.wins) / s.trades)}%` : "—"}</td>
                <td className={`px-2 text-right ${tone(s.pnl_usd)}`}>{usd(s.pnl_usd, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function TradeTable({ d, pageSize = 100 }: { d: PartnersBook; pageSize?: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? d.trades : d.trades.slice(0, pageSize);
  return (
    <Panel>
      <PanelHeader><PanelTitle>Every trade · newest first · {d.trades.length}</PanelTitle></PanelHeader>
      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[40rem] text-[13px] tabular-nums" data-testid="partners-trades">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">bought</th>
              <th className="px-2 text-left font-normal">coin</th>
              <th className="px-2 text-left font-normal">strategy</th>
              <th className="px-2 text-right font-normal">spent</th>
              <th className="px-2 text-right font-normal">result</th>
              <th className="px-2 text-right font-normal">money</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => {
              const money = pnlOf(t);
              const cost = Number(t.cost_usd ?? 0);
              return (
                <tr key={t.id} className="border-t border-line/60">
                  <td className="py-1.5 pr-3 text-ink-3">{dubai(t.opened_at)}</td>
                  <td className="px-2 font-medium">
                    <a href={`https://dexscreener.com/solana/${t.mint_address}`} target="_blank" rel="noreferrer"
                       className="text-accent underline-offset-2 hover:underline">
                      {t.symbol || `${t.mint_address.slice(0, 6)}…`} <span aria-hidden>↗</span>
                    </a>
                  </td>
                  <td className="px-2" title={plain({ id: t.strategy_id ?? "?" })}>{t.strategy_id ?? "—"}</td>
                  <td className="px-2 text-right">{usd(t.cost_usd)}</td>
                  <td className={`px-2 text-right ${money == null ? "text-ink-dim" : tone(money)}`}>
                    {t.status === "OPEN" ? "open" : money == null || !cost ? "—" : pct((100 * Number(money)) / cost)}
                  </td>
                  <td className={`px-2 text-right ${money == null ? "text-ink-dim" : tone(money)}`}>{usd(money, true)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {d.trades.length > pageSize ? (
          <button type="button" onClick={() => setAll((v) => !v)}
                  className="mt-2 text-[12px] text-accent underline-offset-2 hover:underline">
            {all ? "Show the latest 100" : `Show all ${d.trades.length}`}
          </button>
        ) : null}
      </div>
    </Panel>
  );
}

export function PartnersLabPage() {
  const q = useQuery({
    queryKey: ["partners-book"],
    queryFn: () => api.get<PartnersBook>("/real-wallet/partners-book"),
    refetchInterval: 60_000,
  });
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) {
    return <ErrorState title="Could not load the Partners Wallet" body="The page could not reach the API." onRetry={() => void q.refetch()} />;
  }
  const d = q.data;
  return (
    <div className="min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Partners Wallet</h1>
        <p className="text-sm text-ink-3">
          Real money. The main wallet since Karthik and Rafiq went 50-50 on {dubai(d.partners.started_at)} Dubai.
          Closed trades only; SOL&apos;s own price moves are not counted. Updates every minute.
        </p>
      </div>
      <PartnersSummary d={d} />
      <DayTable d={d} />
      <StrategyTable d={d} />
      <TradeTable d={d} />
    </div>
  );
}
