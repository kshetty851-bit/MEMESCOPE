"use client";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";

import { pct, usd } from "./format";
import type { MonthlyMonthOut, MonthlyOut, MonthlySummaryOut } from "./types";

const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
}

const tone = (v: string) => (Number(v) > 0 ? "text-up" : Number(v) < 0 ? "text-down" : "text-ink-3");

function Side({ side }: { side: MonthlyMonthOut["side"] }) {
  return (
    <Badge tone={side === "long" ? "safe" : "danger"} className="px-2 py-0.5 text-xs font-semibold">
      {side === "long" ? "LONG" : "SHORT"}
    </Badge>
  );
}

function Summary({ title, s, testId }: { title: string; s: MonthlySummaryOut; testId: string }) {
  return (
    <div className="rounded-md border border-line/60 px-3 py-2.5" data-testid={testId}>
      <div className="text-label font-medium uppercase text-ink-3">{title}</div>
      <div className={`text-lg font-semibold tabular-nums ${tone(s.total_pnl_usd)}`}>
        {usd(s.total_pnl_usd, { signed: true, digits: 0 })}
      </div>
      <div className="text-xs text-ink-3">
        {s.months} month{s.months === 1 ? "" : "s"} · {s.up} up
        {s.liquidated ? ` · ${s.liquidated} liquidated` : ""}
        {s.best_usd ? ` · best ${usd(s.best_usd, { signed: true, digits: 0 })}` : ""}
        {s.worst_usd ? ` · worst ${usd(s.worst_usd, { signed: true, digits: 0 })}` : ""}
      </div>
    </div>
  );
}

/**
 * THE MONTHLY BOOK (Karthik, 2026-10-09). On the 1st of each month a fresh
 * $1,000 goes LONG if BTC rose last month and SHORT if it fell, at 3x, from the
 * month's first price to its last. Every figure is the API's.
 */
export function MonthlyTab({ data }: { data: MonthlyOut }) {
  const c = data.current;
  return (
    <div className="flex flex-col gap-4" data-testid="monthly">
      <Panel>
        <PanelHeader>
          <PanelTitle>
            This month{c ? ` · ${monthLabel(c.month)}` : ""}
          </PanelTitle>
        </PanelHeader>
        {c ? (
          <div className="grid gap-3 p-3 sm:grid-cols-4" data-testid="monthly-current">
            <div>
              <div className="text-label font-medium uppercase text-ink-3">Position</div>
              <div className="mt-1 flex items-center gap-2">
                <Side side={c.side} />
                <span className="text-sm text-ink-3">{data.leverage}× on {usd(data.capital_usd, { digits: 0 })}</span>
              </div>
            </div>
            <div>
              <div className="text-label font-medium uppercase text-ink-3">Entered / now</div>
              <div className="text-sm tabular-nums">
                {usd(c.entry, { digits: 0 })} → {usd(c.exit, { digits: 0 })}
              </div>
            </div>
            <div>
              <div className="text-label font-medium uppercase text-ink-3">So far</div>
              <div className={`text-lg font-semibold tabular-nums ${tone(c.pnl_usd)}`}>
                {usd(c.pnl_usd, { signed: true })} <span className="text-sm">({pct(c.pct, { signed: true, digits: 1 })})</span>
              </div>
            </div>
            <div>
              <div className="text-label font-medium uppercase text-ink-3">Liquidation at</div>
              <div className="text-sm tabular-nums">{c.liquidated ? "hit this month" : usd(c.liquidation_price, { digits: 0 })}</div>
            </div>
          </div>
        ) : (
          <p className="p-3 text-sm text-ink-3">No candles for this month yet.</p>
        )}
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2">
        <Summary title={`Live since ${monthLabel(data.live_start)} (finished months)`} s={data.live} testId="monthly-live" />
        <Summary title="Backtest, Jan 2024 to the live start" s={data.backtest} testId="monthly-backtest" />
      </div>

      <Panel>
        <PanelHeader>
          <PanelTitle>Every month</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-3">
          <table className="w-full min-w-[34rem] text-[13px] tabular-nums" data-testid="monthly-table">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className="py-1 pr-3 text-left font-normal">month</th>
                <th className="py-1 pr-3 text-left font-normal">side</th>
                <th className="py-1 pr-3 text-right font-normal">entry</th>
                <th className="py-1 pr-3 text-right font-normal">close</th>
                <th className="py-1 pr-3 text-right font-normal">result</th>
                <th className="py-1 text-right font-normal" />
              </tr>
            </thead>
            <tbody>
              {data.months.map((m) => (
                <tr key={m.month} className="border-t border-line/60">
                  <td className="py-1.5 pr-3">{monthLabel(m.month)}</td>
                  <td className="py-1.5 pr-3"><Side side={m.side} /></td>
                  <td className="py-1.5 pr-3 text-right">{usd(m.entry, { digits: 0 })}</td>
                  <td className="py-1.5 pr-3 text-right">{m.running ? `${usd(m.exit, { digits: 0 })} now` : usd(m.exit, { digits: 0 })}</td>
                  <td className={`py-1.5 pr-3 text-right font-medium ${tone(m.pnl_usd)}`}>
                    {usd(m.pnl_usd, { signed: true, digits: 0 })} ({pct(m.pct, { signed: true, digits: 0 })})
                  </td>
                  <td className="py-1.5 text-right text-[11px] text-ink-dim">
                    {m.liquidated ? "liquidated · " : ""}{m.running ? "running" : m.live ? "live" : "backtest"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="max-w-[78ch] text-xs leading-relaxed text-ink-dim" data-testid="monthly-rule">
        The rule: on the 1st of each month (UTC) a fresh {usd(data.capital_usd, { digits: 0 })} goes LONG
        if BTC rose last month and SHORT if it fell, at {data.leverage}×, from the month&apos;s first price to
        its last. Fees {pct(data.fee_pct_per_side)} per side on the leveraged amount; funding is not counted.
        A move of about a third against the position liquidates the month (−{usd(data.capital_usd, { digits: 0 })}).
        {data.enabled ? "" : " Candle collection for this book is switched off, so the latest price may be old."}
      </p>
    </div>
  );
}
