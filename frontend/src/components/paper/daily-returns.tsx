import { Skeleton } from "@/components/ui/skeleton";
import { pct, tone, usd } from "@/lib/paper";
import { cn } from "@/lib/utils";
import type { PaperDailyReturn } from "@/types/paper";

/**
 * DAILY RETURNS
 *
 * The rows come from the completed-trade audit record, not from today's open
 * position marks. A date can therefore be read back tomorrow without a later
 * quote restating what the strategy had completed that day.
 */

function ReturnCell({ value, money = false }: { value: string | null; money?: boolean }) {
  const display = money ? usd(value) : pct(value);
  return (
    <td
      className={cn(
        "py-3 text-right tabular-nums",
        value === null && "text-ink-3",
        tone(value) === "positive" && "text-up",
        tone(value) === "negative" && "text-down",
        tone(value) === "neutral" && value !== null && "text-ink-2",
      )}
    >
      {display ?? "—"}
    </td>
  );
}

export function DailyReturns({
  daily,
  disclosure,
  isPending,
  isError,
}: {
  daily: PaperDailyReturn[];
  disclosure: string;
  isPending: boolean;
  isError: boolean;
}) {
  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-11" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-sm text-ink-3">
        Daily returns are temporarily unavailable. The wallet summary is still current.
      </p>
    );
  }

  if (daily.length === 0) {
    return (
      <p className="text-sm text-ink-3">
        Nothing has closed yet, so there is no completed-trade daily return to report.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line text-label uppercase tracking-wide text-ink-3">
            <th className="py-2 text-left font-medium">Date (UTC)</th>
            <th className="py-2 text-right font-medium">Completed</th>
            <th className="py-2 text-right font-medium">Gross P/L</th>
            <th className="py-2 text-right font-medium">Net P/L</th>
            <th className="py-2 text-right font-medium">Gross return</th>
            <th className="py-2 text-right font-medium">Net return</th>
          </tr>
        </thead>
        <tbody>
          {daily.map((row) => (
            <tr key={row.date} className="border-b border-line/50">
              <td className="py-3 font-medium tabular-nums text-ink">{row.date}</td>
              <td className="py-3 text-right tabular-nums text-ink-2">
                {row.completed_trades}
              </td>
              <ReturnCell value={row.gross_pnl_usd} money />
              <ReturnCell value={row.net_pnl_usd} money />
              <ReturnCell value={row.gross_return_pct} />
              <td
                className="py-3 text-right tabular-nums"
                title={
                  row.cost_unavailable_trades > 0
                    ? `${row.cost_unavailable_trades} completed trade${row.cost_unavailable_trades === 1 ? "" : "s"} could not be costed.`
                    : undefined
                }
              >
                <span
                  className={cn(
                    row.net_return_pct === null && "text-ink-3",
                    tone(row.net_return_pct) === "positive" && "text-up",
                    tone(row.net_return_pct) === "negative" && "text-down",
                    tone(row.net_return_pct) === "neutral" &&
                      row.net_return_pct !== null &&
                      "text-ink-2",
                  )}
                >
                  {pct(row.net_return_pct) ?? "—"}
                </span>
                {row.cost_unavailable_trades > 0 ? (
                  <span className="ml-1 text-xs text-ink-3">
                    ({row.cost_unavailable_trades} uncosted)
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 max-w-3xl text-xs leading-relaxed text-ink-3">
        Returns are each day&apos;s completed-trade P/L relative to the wallet&apos;s
        starting capital, not an intra-day marked equity change. {disclosure}
      </p>
    </div>
  );
}
