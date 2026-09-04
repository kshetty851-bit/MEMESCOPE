"use client";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useCompoundBoard } from "@/hooks/use-lab";

import { SellButton } from "../strategy-lab/sell-button";
import { toneOf } from "../strategy-lab/tone";

/**
 * COMPOUND LAB
 *
 * One $100 wallet trading a frozen rule and taking profit on the WALLET at
 * +10%, then compounding from what it actually realised.
 *
 * The distinction this page has to carry is between the two numbers a cycle
 * produces. A cycle trips on MARKS — cash plus what the book could be sold for
 * — and then the book is actually sold, which pays impact. What is banked is
 * the second figure, and the next cycle compounds from it. Showing only the
 * target would flatter every cycle by exactly the cost of trading.
 *
 * Research simulation. No real order was ever placed.
 */

function money(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `$${v.toFixed(digits)}`;
}

function signed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

export default function CompoundLabPage() {
  const { data, isLoading, error } = useCompoundBoard();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !data) return <ErrorState body="Compound Lab unavailable." />;

  if (!data.activated) {
    return (
      <Panel density="compact">
        <Label>COMPOUND LAB</Label>
        <p className="mt-2 text-sm text-ink">Not started yet.</p>
        <p className="mt-1 text-xs text-muted">
          The wallet opens at {money(data.starting_equity)} and banks each time
          it is up {((data.target_multiple - 1) * 100).toFixed(0)}%. It begins
          on the first tick after the feature is switched on.
        </p>
      </Panel>
    );
  }

  const open = data.positions.filter((p) => p.status === "open");
  const progress =
    data.current_cycle && data.equity !== undefined
      ? (data.equity - data.current_cycle.base_usd) /
        (data.current_cycle.target_usd - data.current_cycle.base_usd)
      : null;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <Label>COMPOUND LAB</Label>
            <h1 className="mt-1 text-lg font-medium text-ink">
              {data.strategy_id} {data.name} · {money(data.starting_equity, 0)}{" "}
              START · BANK AT +
              {((data.target_multiple - 1) * 100).toFixed(0)}%
            </h1>
            <p className="mt-1 text-xs font-medium tracking-wide text-warn">
              PAPER / RESEARCH ONLY — REAL MONEY OFF
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs sm:grid-cols-4">
            <div>
              <dt className="text-muted">Equity</dt>
              <dd className={`font-mono ${toneOf((data.equity ?? 0) - data.starting_equity)}`}>
                {money(data.equity)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Cash</dt>
              <dd className="font-mono text-ink">{money(data.cash)}</dd>
            </div>
            <div>
              <dt className="text-muted">Cycles banked</dt>
              <dd className="font-mono text-ink">{data.cycles_banked ?? 0}</dd>
            </div>
            <div>
              <dt className="text-muted">Open</dt>
              <dd className="font-mono text-ink">{open.length}</dd>
            </div>
          </dl>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-muted">
          {data.disclosure}
        </p>
      </Panel>

      {data.rules ? (
        <Panel density="compact">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <Label>
              THE STRATEGY — {data.rules.id} {data.rules.name}
            </Label>
            <p className="font-mono text-[10px] text-muted">
              frozen · registry {data.spec_hash.slice(0, 12)}…
            </p>
          </div>
          <p className="mt-1 text-xs text-ink-3">{data.rules.hypothesis}</p>

          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">
                Buys when, at {data.rules.checkpoint_label}
              </p>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                {data.rules.entry_text.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">
                Sells when
              </p>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                {/* The wallet target is not in `exit_text`: it is not a rule
                    the position carries. Named first because it is the exit
                    that defines this lab. */}
                <li className="text-accent">
                  · the WALLET reaches +
                  {((data.target_multiple - 1) * 100).toFixed(0)}% (
                  {money(data.current_cycle?.target_usd)}) — sells everything
                </li>
                {data.rules.exit_text.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-2 font-mono text-[10px] text-muted">
            <span>size {money(Number(data.rules.size_usd))} per position</span>
            <span>max {data.rules.max_concurrent} at once</span>
            <span>
              max exposure {money(Number(data.rules.max_exposure_usd))}
            </span>
            <span>no take-profit per position — the wallet target is the exit</span>
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-warn">
            Chosen because FLOW was the only V7 family above the cash control —
            on five to seven closed trades per arm. That is a hypothesis, not a
            measured edge: V6-07 showed a 3.0 profit factor on twenty-three
            trades and ended at −25%. Overfit risk {data.rules.overfit_risk}.
          </p>
        </Panel>
      ) : null}

      {data.current_cycle ? (
        <Panel density="compact">
          <Label>CYCLE {data.current_cycle.cycle_no} — IN PROGRESS</Label>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-8 gap-y-1 font-mono text-xs text-ink">
            <span>base {money(data.current_cycle.base_usd)}</span>
            <span>target {money(data.current_cycle.target_usd)}</span>
            <span className={toneOf((data.equity ?? 0) - data.current_cycle.base_usd)}>
              now {money(data.equity)}
            </span>
            {progress !== null ? (
              <span className="text-muted">
                {(progress * 100).toFixed(1)}% of the way
              </span>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <Label>OPEN POSITIONS ({open.length})</Label>
          <p className="text-[10px] text-muted">
            Selling by hand records the exit as{" "}
            <span className="font-mono">manual_close</span>; the wallet target
            records <span className="font-mono">cycle_target</span>.
          </p>
        </div>
        {open.length === 0 ? (
          <p className="mt-2 text-xs text-muted">Nothing open right now.</p>
        ) : (
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-normal">sell</th>
                  <th className="py-1 pr-3 font-normal">mint</th>
                  <th className="py-1 pr-3 text-right font-normal">size</th>
                  <th className="py-1 pr-3 text-right font-normal">value</th>
                  <th className="py-1 pr-3 text-right font-normal">exec ×</th>
                  <th className="py-1 font-normal">opened</th>
                </tr>
              </thead>
              <tbody className="text-ink">
                {open.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-1 pr-3">
                      <SellButton id={p.id} />
                    </td>
                    <td className="py-1 pr-3">{p.mint.slice(0, 8)}…</td>
                    <td className="py-1 pr-3 text-right">{money(p.size_usd)}</td>
                    <td className="py-1 pr-3 text-right">{money(p.open_value)}</td>
                    <td className="py-1 pr-3 text-right">
                      {p.exec_multiple === null
                        ? "—"
                        : `${p.exec_multiple.toFixed(3)}×`}
                    </td>
                    <td className="py-1">
                      {p.opened_at.slice(5, 16).replace("T", " ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel density="compact">
        <Label>CYCLE LEDGER ({data.cycles.length})</Label>
        <p className="mt-1 text-[10px] text-muted">
          <span className="text-ink">Aimed at</span> is equity on marks when the
          target tripped. <span className="text-ink">Banked</span> is what the
          wallet actually realised after selling the book — and it is what the
          next cycle compounds from.
        </p>
        <div className="mt-2 max-h-72 overflow-auto">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">#</th>
                <th className="py-1 pr-3 text-right font-normal">base</th>
                <th className="py-1 pr-3 text-right font-normal">target</th>
                <th className="py-1 pr-3 text-right font-normal">aimed at</th>
                <th className="py-1 pr-3 text-right font-normal">banked</th>
                <th className="py-1 pr-3 text-right font-normal">gain</th>
                <th className="py-1 pr-3 text-right font-normal">sold</th>
                <th className="py-1 font-normal">outcome</th>
              </tr>
            </thead>
            <tbody className="text-ink">
              {data.cycles.map((c) => (
                <tr key={c.cycle_no} className="border-t border-line">
                  <td className="py-1 pr-3">{c.cycle_no}</td>
                  <td className="py-1 pr-3 text-right">{money(c.base_usd)}</td>
                  <td className="py-1 pr-3 text-right">{money(c.target_usd)}</td>
                  <td className="py-1 pr-3 text-right">
                    {money(c.equity_at_target)}
                  </td>
                  <td className="py-1 pr-3 text-right">
                    {money(c.realised_equity)}
                  </td>
                  <td
                    className={`py-1 pr-3 text-right ${
                      c.realised_equity === null
                        ? ""
                        : toneOf(c.realised_equity - c.base_usd)
                    }`}
                  >
                    {c.realised_equity === null
                      ? "—"
                      : signed(c.realised_equity - c.base_usd)}
                  </td>
                  <td className="py-1 pr-3 text-right">{c.positions_closed}</td>
                  <td className="py-1">{c.outcome ?? "running"}</td>
                </tr>
              ))}
              {data.cycles.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-2 text-muted">
                    No cycle has completed yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
