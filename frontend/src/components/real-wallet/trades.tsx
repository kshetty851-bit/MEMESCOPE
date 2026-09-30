"use client";

import { useEffect, useState } from "react";

/**
 * A wallet's trades and its "since the first trade" card, shared by the main
 * real wallet page and every user wallet's page (Karthik, 2026-09-30: "user 1
 * dashboard should be same as real wallet").
 */

export type Position = {
  id: string;
  mint_address: string;
  symbol: string | null;
  status: string;
  strategy_id: string | null;
  quantity: string;
  cost_usd: string;
  spent: string | null;
  received: string | null;
  realised_gross_pnl_usd: string | null;
  realised_net_pnl_usd: string | null;
  exit_reason: string | null;
  exit_state: string | null;
  opened_at: string;
  closed_at: string | null;
  entry_signature: string | null;
  exit_signature: string | null;
};

/** Every real trade since the first, from the server — not the latest 50. */
export type SinceFirstTrade = {
  first_trade_at: string;
  trades: number;
  won: number;
  lost: number;
  open: number;
  net_pnl_usd: string;
  traded_usd: string;
  average_return_pct: string | null;
  start_balance_sol: string | null;
  start_value_usd: string | null;
  return_pct: string | null;
};

export const usd = (value: number) =>
  `${value < 0 ? "−" : ""}$${Math.abs(value).toFixed(2)}`;

export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const EXIT_STATE: Record<string, string> = {
  created: "selling",
  safety_approved: "selling",
  order_created: "selling",
  submitted: "sell sent",
  blocked: "sell refused — retrying",
  failed: "sell failed — retrying",
  reconciliation_required: "sell needs checking",
};

/** What a closed trade made, net of fees when that is known. */
function resultOf(p: Position): number | null {
  const value = p.realised_net_pnl_usd ?? p.realised_gross_pnl_usd;
  return value == null ? null : Number(value);
}

/** How long a trade was held — a live clock while it is still open. */
function Held({ from, to }: { from: string; to: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (to) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [to]);
  const end = to ? new Date(to).getTime() : now;
  const secs = Math.max(0, Math.floor((end - new Date(from).getTime()) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  const text =
    secs >= 86400
      ? `${Math.floor(secs / 86400)}d ${pad(Math.floor((secs % 86400) / 3600))}h`
      : secs >= 3600
        ? `${Math.floor(secs / 3600)}h ${pad(Math.floor((secs % 3600) / 60))}m`
        : `${Math.floor(secs / 60)}m ${pad(secs % 60)}s`;
  return <span className="tabular-nums">{text}</span>;
}

function TokenLink({ p }: { p: Position }) {
  return (
    <a
      className="text-ink underline decoration-dotted"
      href={`https://dexscreener.com/solana/${p.mint_address}`}
      rel="noreferrer"
      target="_blank"
      title={p.mint_address}
    >
      {p.symbol ?? p.mint_address.slice(0, 8)}
    </a>
  );
}

function TxLinks({ p }: { p: Position }) {
  const links = [
    ["buy", p.entry_signature],
    ["sell", p.exit_signature],
  ].filter((x): x is [string, string] => Boolean(x[1]));
  if (!links.length) return <>—</>;
  return (
    <span className="flex gap-2">
      {links.map(([label, sig]) => (
        <a
          key={label}
          className="text-accent underline decoration-dotted"
          href={`https://solscan.io/tx/${sig}`}
          rel="noreferrer"
          target="_blank"
        >
          {label}
        </a>
      ))}
    </span>
  );
}

/** A live d HH:MM:SS clock counting up from `from`. */
function Clock({ from }: { from: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const secs = Math.max(0, Math.floor((now - new Date(from).getTime()) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  const days = Math.floor(secs / 86400);
  return (
    <span className="tabular-nums">
      {days ? `${days}d ` : ""}
      {pad(Math.floor((secs % 86400) / 3600))}:{pad(Math.floor((secs % 3600) / 60))}:
      {pad(secs % 60)}
    </span>
  );
}

const pct = (value: string | null) =>
  value == null
    ? "—"
    : `${Number(value) >= 0 ? "+" : "−"}${Math.abs(Number(value)).toFixed(2)}%`;

const tone = (value: number) =>
  value > 0 ? "text-up" : value < 0 ? "text-down" : "text-ink";

/**
 * The wallet since it began trading: how long, what it made, and what that is
 * on the wallet's worth at the first buy — the lab's "since first trade", with
 * real money. Totals are the server's, over every trade.
 */
export function SinceFirstTradeCard({ since }: { since: SinceFirstTrade | null | undefined }) {
  if (!since) return null;
  const pnl = Number(since.net_pnl_usd);
  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-ink-3">Since the first trade</p>
        <p className="text-sm text-ink-3">
          <span className="rounded bg-ink/[0.06] px-1.5 py-px font-mono text-ink">
            <Clock from={since.first_trade_at} />
          </span>{" "}
          since {when(since.first_trade_at)}
        </p>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-ink-3">Profit after fees</p>
          <p className={`text-2xl font-medium tabular-nums ${tone(pnl)}`}>
            {pnl > 0 ? "+" : ""}
            {usd(pnl)}
          </p>
          <p className="text-xs text-ink-3">
            {since.trades} trades · {since.won} won · {since.lost} lost
            {since.open ? ` · ${since.open} open` : ""}
          </p>
        </div>
        <div>
          <p className="text-xs text-ink-3">Return on the wallet</p>
          <p
            className={`text-2xl font-medium tabular-nums ${tone(Number(since.return_pct ?? 0))}`}
          >
            {pct(since.return_pct)}
          </p>
          <p className="text-xs text-ink-3">
            {since.start_value_usd && since.start_balance_sol
              ? `on $${Number(since.start_value_usd).toFixed(2)} (${Number(
                  since.start_balance_sol,
                ).toFixed(4)} SOL) when trading began`
              : "the wallet's starting worth was not recorded"}
          </p>
        </div>
        <div>
          <p className="text-xs text-ink-3">Average per trade</p>
          <p
            className={`text-2xl font-medium tabular-nums ${tone(
              Number(since.average_return_pct ?? 0),
            )}`}
          >
            {pct(since.average_return_pct)}
          </p>
          <p className="text-xs text-ink-3">
            on ${Number(since.traded_usd).toFixed(2)} traded
          </p>
        </div>
      </div>
    </section>
  );
}

const sol = (value: string | null) => (value ? `${Number(value).toFixed(4)} SOL` : "—");

/**
 * Every real trade, laid out like the Graduation Lab's own panel: what is open
 * now, what closed and how, and the totals. Figures are the wallet's settled
 * amounts; the server sends its latest 50.
 */
export function TradesTable({ positions }: { positions: Position[] }) {
  const open = positions.filter((p) => p.status === "OPEN");
  const closed = positions.filter((p) => p.status !== "OPEN");
  const results = closed.map(resultOf).filter((r): r is number => r !== null);
  const net = results.reduce((a, b) => a + b, 0);
  const won = results.filter((r) => r > 0).length;
  const lost = results.filter((r) => r < 0).length;
  const grossOnly = closed.filter(
    (p) => p.realised_net_pnl_usd == null && p.realised_gross_pnl_usd != null,
  ).length;
  const head = "border-y border-line text-left text-xs text-ink-3";

  return (
    <section className="mt-6 rounded-lg border border-line">
      <div className="flex flex-wrap items-baseline justify-between gap-2 p-4">
        <p className="text-label text-ink-3">Real trades</p>
        {positions.length ? (
          <p className="text-sm text-ink-3">
            {closed.length} closed · {won} won · {lost} lost ·{" "}
            <span className={net > 0 ? "text-up" : net < 0 ? "text-down" : "text-ink"}>
              {usd(net)}
            </span>
            {grossOnly ? ` (${grossOnly} before fees)` : ""} · {open.length} open
            {positions.length >= 50 ? " · latest 50 shown" : ""}
          </p>
        ) : null}
      </div>
      {!positions.length ? (
        <p className="px-4 pb-4 text-sm text-ink-3">No real trades yet.</p>
      ) : null}

      {open.length ? (
        <div className="overflow-x-auto">
          <p className="px-4 pb-2 text-xs uppercase tracking-wide text-ink-3">
            Open — {open.length}
          </p>
          <table className="w-full min-w-[640px] text-sm">
            <thead className={head}>
              <tr>
                <th className="p-3 font-normal">Token</th>
                <th className="font-normal">Held</th>
                <th className="font-normal">State</th>
                <th className="font-normal">Spent</th>
                <th className="font-normal">Bought</th>
                <th className="font-normal">Arm</th>
                <th className="p-3 font-normal">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.id} className="border-b border-line-subtle last:border-0">
                  <td className="p-3">
                    <TokenLink p={p} />
                  </td>
                  <td>
                    <Held from={p.opened_at} to={null} />
                  </td>
                  <td className="text-ink-3">
                    {(p.exit_state && EXIT_STATE[p.exit_state]) || "holding"}
                  </td>
                  <td className="tabular-nums">{sol(p.spent)}</td>
                  <td className="tabular-nums text-ink-3">{when(p.opened_at)}</td>
                  <td className="text-ink-3">{p.strategy_id ?? "—"}</td>
                  <td className="p-3">
                    <TxLinks p={p} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {closed.length ? (
        <div className="overflow-x-auto">
          <p className="px-4 pb-2 pt-3 text-xs uppercase tracking-wide text-ink-3">
            Closed — {closed.length}
          </p>
          <table className="w-full min-w-[860px] text-sm">
            <thead className={head}>
              <tr>
                <th className="p-3 font-normal">Token</th>
                <th className="font-normal">Result</th>
                <th className="font-normal">Return</th>
                <th className="font-normal">Held</th>
                <th className="font-normal">How it ended</th>
                <th className="font-normal">Spent</th>
                <th className="font-normal">Got back</th>
                <th className="font-normal">Bought</th>
                <th className="font-normal">Sold</th>
                <th className="font-normal">Arm</th>
                <th className="p-3 font-normal">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((p) => {
                const result = resultOf(p);
                const cost = Number(p.cost_usd);
                const tone =
                  result == null ? "text-ink-3" : result >= 0 ? "text-up" : "text-down";
                return (
                  <tr key={p.id} className="border-b border-line-subtle last:border-0">
                    <td className="p-3">
                      <TokenLink p={p} />
                    </td>
                    <td className={`tabular-nums ${tone}`}>
                      {result == null ? "—" : usd(result)}
                      {result != null && p.realised_net_pnl_usd == null ? (
                        <span className="text-xs text-ink-3"> before fees</span>
                      ) : null}
                    </td>
                    <td className={`tabular-nums ${tone}`}>
                      {result == null || !(cost > 0)
                        ? "—"
                        : `${result >= 0 ? "+" : "−"}${Math.abs((result / cost) * 100).toFixed(2)}%`}
                    </td>
                    <td>
                      {p.closed_at ? <Held from={p.opened_at} to={p.closed_at} /> : "—"}
                    </td>
                    <td className="text-ink-3">
                      {p.exit_reason?.startsWith("time")
                        ? "sold on time"
                        : `sold · ${p.exit_reason ?? "closed"}`}
                    </td>
                    <td className="tabular-nums">{sol(p.spent)}</td>
                    <td className="tabular-nums">{sol(p.received)}</td>
                    <td className="tabular-nums text-ink-3">{when(p.opened_at)}</td>
                    <td className="tabular-nums text-ink-3">
                      {p.closed_at ? when(p.closed_at) : "—"}
                    </td>
                    <td className="text-ink-3">{p.strategy_id ?? "—"}</td>
                    <td className="p-3">
                      <TxLinks p={p} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
