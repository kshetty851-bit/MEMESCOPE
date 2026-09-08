"use client";

import { Label, Panel } from "@/components/ui/panel";
import { useGraduationPaper } from "@/hooks/use-graduation";
import type { PaperHorizon } from "@/types/graduation";

/**
 * A simulated $100 book over the graduation cohort.
 *
 * The two equity columns are shown TOGETHER and always. On this population
 * they disagree completely — at fifteen minutes the book read +$82 while one
 * coin doing 14.4x was that entire result, and removing it left -$51. A page
 * that showed only the headline would be lying by omission, and every false
 * edge this platform has produced had exactly that shape.
 *
 * Nothing here is traded.
 */

function money(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(2)}`;
}

function tone(v: number | null | undefined, base = 100): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function Row({ h }: { h: PaperHorizon }) {
  const carried =
    h.trades > 0 && h.final_equity_net > 100 && h.final_equity_without_best <= 100;
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 pr-3 font-mono text-ink">+{h.minutes}m</td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{h.trades}</td>
      <td className={`py-1.5 pr-3 text-right font-mono ${tone(h.final_equity_net)}`}>
        {money(h.final_equity_net)}
      </td>
      <td
        className={`py-1.5 pr-3 text-right font-mono ${tone(h.final_equity_without_best)}`}
      >
        {money(h.final_equity_without_best)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-[10px] text-muted">
        {h.best_trade_multiple ? `${h.best_trade_multiple.toFixed(1)}x` : "—"}
      </td>
      <td className="py-1.5 text-[10px] text-muted">
        {carried ? (
          <span className="text-warn">carried by one trade</span>
        ) : (
          `${h.skipped_no_mark_yet} pending · ${h.excluded_glitch} glitch`
        )}
      </td>
    </tr>
  );
}

export function GraduationPaperPanel() {
  const { data, isLoading, error } = useGraduationPaper();
  if (isLoading || error || !data) return null;

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Label>SIMULATED ${data.book_usd} BOOK — BUY EVERY GRADUATION</Label>
        <span className="font-mono text-[10px] text-muted">
          ${data.position_usd} × {data.max_concurrent} · {data.cohort} coins
        </span>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="text-[10px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">sell at</th>
              <th className="py-1 pr-3 text-right font-normal">trades</th>
              <th className="py-1 pr-3 text-right font-normal">book</th>
              <th className="py-1 pr-3 text-right font-normal" title="The same book with its single best trade removed.">
                minus best
              </th>
              <th className="py-1 pr-3 text-right font-normal">best</th>
              <th className="py-1 font-normal" />
            </tr>
          </thead>
          <tbody>
            {data.horizons.map((h) => (
              <Row key={h.minutes} h={h} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
        <span className="text-ink">Read the two equity columns together.</span>{" "}
        Where they disagree, the strategy has not been shown to work — it has
        been shown to have had a trade. Horizons are also NOT comparable with
        each other: a coin only appears once it is old enough for that mark, so
        each column is a different set of coins.
      </p>

      <p className="mt-2 text-[10px] leading-relaxed text-muted">{data.disclosure}</p>
    </Panel>
  );
}
