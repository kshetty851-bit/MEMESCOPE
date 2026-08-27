"use client";

import Link from "next/link";

import { Label, Panel } from "@/components/ui/panel";
import { Stat } from "@/components/ui/stat";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { usePaperV2 } from "@/hooks/use-paper-v2";
import { countdown, v2pct, v2usd } from "@/lib/paper-v2";
import { cn } from "@/lib/utils";

/**
 * PAPER WALLET V2 — a separate experiment, on separate capital.
 *
 * This page never renders a V1 figure. V2 has its own endpoint, its own
 * wallet row and its own $1,000 of new simulated capital; the two wallets are
 * comparable but never combined, and the switcher at the top exists so a
 * reader can move between them without either page pretending to be the other.
 *
 * The EXPERIMENTAL badge is not decoration. V2 has no stop loss: a position can
 * fall to nothing, and the page is built to show that at the same size as a win.
 */

function Switcher({ current }: { current: "v1" | "v2" }) {
  const base =
    "px-3 py-1.5 text-xs font-medium tracking-wide uppercase transition-colors";
  return (
    <div className="inline-flex rounded-md border border-border overflow-hidden">
      <Link
        href="/wallet"
        className={cn(base, current === "v1"
          ? "bg-foreground text-background"
          : "text-muted-foreground hover:text-foreground")}
      >
        Original
      </Link>
      <Link
        href="/wallet-v2"
        className={cn(base, "border-l border-border", current === "v2"
          ? "bg-amber-500 text-black"
          : "text-muted-foreground hover:text-foreground")}
      >
        V2 Experimental
      </Link>
    </div>
  );
}

function TargetPips({ status }: { status: string[] }) {
  const labels = ["1.25x", "1.50x", "1.75x"];
  return (
    <span className="inline-flex gap-1">
      {status.map((s, i) => (
        <span
          key={i}
          title={`${labels[i] ?? `rung ${i}`}: ${s}`}
          className={cn(
            "px-1.5 py-0.5 rounded text-[10px] font-mono",
            s === "filled"
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-muted text-muted-foreground",
          )}
        >
          {labels[i] ?? i}
        </span>
      ))}
    </span>
  );
}

export default function PaperWalletV2Page() {
  const { data, isLoading, isError, refetch } = usePaperV2();

  if (isLoading) return <Skeleton className="h-96 w-full" />;
  if (isError || !data) return (
      <ErrorState
        body="Paper Wallet V2 could not be read."
        onRetry={() => void refetch()}
      />
    );

  const m = data.metrics;
  const open = data.positions.filter((p) => p.status === "open");
  const closed = data.positions.filter((p) => p.status === "closed");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">PAPER WALLET V2</h1>
          <span className="rounded bg-amber-500 px-2 py-0.5 text-[10px] font-bold uppercase text-black">
            Experimental
          </span>
          <span className="rounded border border-border px-2 py-0.5 text-[10px] uppercase text-muted-foreground">
            {data.mode.replace("_", " ")}
          </span>
        </div>
        <Switcher current="v2" />
      </div>

      <Panel>
        <Label>Strategy</Label>
        <p className="font-mono text-sm">{data.strategy.summary}</p>
      </Panel>

      {!data.started ? (
        <Panel>
          <p className="text-sm text-muted-foreground">
            V2 has not been started. It holds no capital and has taken no trade.
            Set <code className="font-mono">PAPER_V2_MODE</code> to{" "}
            <code className="font-mono">observe</code> or{" "}
            <code className="font-mono">paper_active</code> to begin.
          </p>
        </Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Starting capital" value={v2usd(m.starting_balance)} />
            <Stat label="Full equity" value={v2usd(m.equity)} />
            <Stat label="Available cash" value={v2usd(m.cash)} />
            <Stat label="Capital allocated" value={v2usd(m.capital_allocated)} />
            <Stat label="Realized P&L" value={v2usd(m.realised_pnl)} />
            <Stat label="Unrealized P&L" value={v2usd(m.unrealised_pnl)} />
            <Stat label="Open positions" value={String(m.open_positions)} />
            <Stat label="Closed positions" value={String(m.closed_positions)} />
            <Stat label="Win rate" value={v2pct(m.win_rate_pct)} />
            <Stat label="Profit factor" value={m.profit_factor ?? "—"} />
            <Stat label="Max drawdown" value={v2pct(m.max_drawdown_pct)} />
            <Stat label="Utilisation" value={v2pct(m.capital_utilisation_pct)} />
          </div>

          <Panel>
            <Label>Open positions ({open.length})</Label>
            {open.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing open.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3">Token</th>
                      <th className="pr-3">Entry</th>
                      <th className="pr-3">Multiple</th>
                      <th className="pr-3">Value</th>
                      <th className="pr-3">Remaining</th>
                      <th className="pr-3">Targets</th>
                      <th className="pr-3">Runner</th>
                      <th className="pr-3">Banked</th>
                      <th className="pr-3">Unrealized</th>
                      <th className="pr-3">6h in</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {open.map((p) => (
                      <tr key={p.mint_address} className="border-t border-border">
                        <td className="py-2 pr-3">{p.mint_address.slice(0, 8)}…</td>
                        <td className="pr-3">{p.opened_at.slice(11, 16)}</td>
                        <td className="pr-3">
                          {p.current_multiple
                            ? `${Number(p.current_multiple).toFixed(3)}x`
                            : "—"}
                        </td>
                        <td className="pr-3">{v2usd(p.position_value)}</td>
                        <td className="pr-3">{v2pct(p.remaining_pct)}</td>
                        <td className="pr-3"><TargetPips status={p.target_status} /></td>
                        <td className="pr-3">{v2pct(p.runner_pct)}</td>
                        <td className="pr-3">{v2usd(p.realised_proceeds)}</td>
                        <td className="pr-3">{v2usd(p.unrealised_pnl)}</td>
                        <td className="pr-3">{countdown(p.seconds_to_expiry)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel>
            <Label>V2 track record ({closed.length})</Label>
            {closed.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No completed V2 trade yet. This record is V2&apos;s alone and is
                never mixed into the original wallet&apos;s track record.
              </p>
            ) : (
              <ul className="space-y-3">
                {closed.map((p) => (
                  <li key={p.mint_address} className="border-t border-border pt-2">
                    <div className="flex justify-between font-mono text-xs">
                      <span>{p.mint_address.slice(0, 10)}…</span>
                      <span className="uppercase text-muted-foreground">
                        {p.final_exit_reason ?? "—"}
                      </span>
                    </div>
                    <ul className="mt-1 space-y-0.5 font-mono text-xs text-muted-foreground">
                      <li>ENTRY {v2usd(p.initial_notional)}</li>
                      {p.fills.map((f, i) => (
                        <li key={i}>
                          {f.rung_index === null
                            ? `${f.reason.toUpperCase()} sold remainder`
                            : `${["1.25x", "1.50x", "1.75x"][f.rung_index] ?? f.rung_index} sold 25%`}{" "}
                          → {v2usd(f.net_proceeds)} net
                        </li>
                      ))}
                      <li className="text-foreground">
                        Total proceeds {v2usd(p.realised_proceeds)}
                      </li>
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      )}

      <p className="text-xs text-muted-foreground">{data.disclosure}</p>
    </div>
  );
}
