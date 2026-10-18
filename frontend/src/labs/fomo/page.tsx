"use client";

import { useQuery } from "@tanstack/react-query";

import { Panel } from "@/components/ui/panel";
import { api } from "@/lib/api-client";

interface Leader {
  rank: number;
  user_id: string;
  handle: string;
  wallet: string;
  pnl_24h_usd: string | null;
  follow_from: string;
}

interface Position {
  id: string;
  wallet: string;
  mint: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  spent_usd: string;
  value_usd: string | null;
  pnl_usd: string | null;
  last_mark_at: string | null;
}

interface Signal {
  signature: string;
  wallet: string;
  mint: string;
  side: string;
  traded_at: string;
  outcome: string;
}

interface Board {
  enabled: boolean;
  configured: boolean;
  running: boolean;
  reason?: string;
  note: string;
  starting_usd: string;
  trade_usd: string;
  started_at?: string;
  roster_at?: string | null;
  source_captured_at?: string | null;
  feed_at?: string | null;
  feed_error?: string | null;
  cash_usd?: string;
  open_value_usd?: string;
  equity_usd?: string;
  pnl_usd?: string;
  open_trades?: number;
  stale_marks?: number;
  leaders?: Leader[];
  positions?: Position[];
  signals?: Signal[];
}

function usd(value?: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString(undefined, { style: "currency", currency: "USD" })
    : "—";
}

function time(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function short(value: string): string {
  return `${value.slice(0, 5)}…${value.slice(-5)}`;
}

export function FomoLabPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["fomo-lab", "board"],
    queryFn: () => api.get<Board>("/labs/fomo/board"),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-5 pb-12">
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-[0.18em] text-ink-dim">
          Strategy / Research simulation
        </p>
        <h1 className="text-3xl font-semibold text-ink">FOMO Lab</h1>
        <p className="max-w-3xl text-sm text-ink-dim">
          One $500 paper book follows the top 20 fomo.family traders by rolling 24-hour
          P&amp;L. Each observed buy opens a $50 lot when cash and a fresh price are
          available. Each sell closes one matching lot. The roster refreshes every 30
          minutes; swaps are checked every two.
        </p>
      </header>

      {isLoading && <Panel>Loading the paper book…</Panel>}
      {error && <Panel>Could not load the FOMO Lab board.</Panel>}
      {data && !data.running && (
        <Panel>
          <p className="font-medium text-ink">Lab is not running</p>
          <p className="mt-1 text-sm text-ink-dim">
            {data.reason === "feed_key_missing"
              ? "The FOMO API key is required."
              : data.reason === "awaiting_first_roster"
                ? "Waiting for the first valid 24-hour leaderboard."
                : "The FOMO Lab feature flag is off."}
          </p>
        </Panel>
      )}
      {data?.running && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Equity", usd(data.equity_usd)],
              ["P/L", usd(data.pnl_usd)],
              ["Cash", usd(data.cash_usd)],
              ["Open lots", `${data.open_trades ?? 0} / 10`],
            ].map(([label, value]) => (
              <Panel key={label}>
                <div className="text-xs uppercase tracking-wider text-ink-dim">{label}</div>
                <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
              </Panel>
            ))}
          </div>
          <Panel>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-dim">
              <span>Started {time(data.started_at)}</span>
              <span>Roster fetched {time(data.roster_at)}</span>
              <span>Source snapshot {time(data.source_captured_at)}</span>
              <span>Last complete swap poll {time(data.feed_at)}</span>
              <span>{data.stale_marks ?? 0} stale open marks</span>
            </div>
            {data.feed_error && (
              <p className="mt-3 text-sm text-danger">Feed issue: {data.feed_error}</p>
            )}
            <p className="mt-3 text-sm text-ink-dim">{data.note}</p>
          </Panel>

          <Panel>
            <h2 className="mb-3 text-lg font-semibold text-ink">Following now</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="text-xs uppercase text-ink-dim">
                  <tr>
                    <th className="py-2">Rank</th>
                    <th>Trader</th>
                    <th>Solana wallet</th>
                    <th>24h P/L reported by source</th>
                    <th>Following since</th>
                  </tr>
                </thead>
                <tbody>
                  {data.leaders?.map((leader) => (
                    <tr key={leader.user_id} className="border-t border-line">
                      <td className="py-2">#{leader.rank}</td>
                      <td>{leader.handle}</td>
                      <td>
                        <a
                          className="text-accent hover:underline"
                          href={`https://solscan.io/account/${leader.wallet}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {short(leader.wallet)}
                        </a>
                      </td>
                      <td>{usd(leader.pnl_24h_usd)}</td>
                      <td>{time(leader.follow_from)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel>
            <h2 className="mb-3 text-lg font-semibold text-ink">Paper lots</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[600px] text-left text-sm">
                <thead className="text-xs uppercase text-ink-dim">
                  <tr>
                    <th className="py-2">Token</th>
                    <th>Trader wallet</th>
                    <th>Status</th>
                    <th>Spent</th>
                    <th>Value / proceeds</th>
                    <th>P/L</th>
                    <th>Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions?.map((pos) => (
                    <tr key={pos.id} className="border-t border-line">
                      <td className="py-2">
                        <a
                          className="text-accent hover:underline"
                          href={`https://solscan.io/token/${pos.mint}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {short(pos.mint)}
                        </a>
                      </td>
                      <td>{short(pos.wallet)}</td>
                      <td>{pos.status}</td>
                      <td>{usd(pos.spent_usd)}</td>
                      <td>{usd(pos.value_usd)}</td>
                      <td>{usd(pos.pnl_usd)}</td>
                      <td>{time(pos.opened_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.positions?.length && (
              <p className="text-sm text-ink-dim">No copied trades yet.</p>
            )}
          </Panel>

          <Panel>
            <h2 className="mb-3 text-lg font-semibold text-ink">
              Observed swaps and decisions
            </h2>
            <div className="max-h-[480px] overflow-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="text-xs uppercase text-ink-dim">
                  <tr>
                    <th className="py-2">When</th>
                    <th>Trader</th>
                    <th>Side</th>
                    <th>Token</th>
                    <th>Outcome</th>
                    <th>Transaction</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signals?.map((signal) => (
                    <tr
                      key={`${signal.wallet}-${signal.signature}-${signal.mint}`}
                      className="border-t border-line"
                    >
                      <td className="py-2">{time(signal.traded_at)}</td>
                      <td>{short(signal.wallet)}</td>
                      <td>{signal.side}</td>
                      <td>{short(signal.mint)}</td>
                      <td>{signal.outcome.replaceAll("_", " ")}</td>
                      <td>
                        <a
                          className="text-accent hover:underline"
                          href={`https://solscan.io/tx/${signal.signature}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {short(signal.signature)}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.signals?.length && (
              <p className="text-sm text-ink-dim">No swaps observed since activation.</p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
