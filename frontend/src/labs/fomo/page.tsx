"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

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
  max_open_trades?: number;
  leaders?: Leader[];
  positions?: Position[];
  signals?: Signal[];
  /** The multiple-traders book (2026-10-19). */
  consensus?: Consensus | null;
}

interface Consensus {
  started_at: string;
  cash_usd: string;
  open_value_usd: string;
  equity_usd: string;
  pnl_usd: string;
  open_trades: number;
  positions: Position[];
  decisions: Record<string, number>;
}


function usd(value?: string | null, signed = false): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const body = Math.abs(n).toLocaleString("en-US", { style: "currency", currency: "USD" });
  return n < 0 ? `-${body}` : signed && n > 0 ? `+${body}` : body;
}

const tone = (value?: string | null) =>
  Number(value) > 0 ? "text-up" : Number(value) < 0 ? "text-down" : "text-ink-dim";

function time(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function short(value: string): string {
  return `${value.slice(0, 5)}…${value.slice(-5)}`;
}

/** Minutes since a timestamp, for the feed lights. */
function ageMinutes(value?: string | null): number | null {
  return value ? (Date.now() - Date.parse(value)) / 60_000 : null;
}

/** What each decision means, and its colour. */
const OUTCOMES: Record<string, { cls: string; label?: string }> = {
  opened: { cls: "bg-up/15 text-up ring-up/30" },
  closed: { cls: "bg-accent/15 text-accent ring-accent/30" },
  pending_price: { cls: "bg-warn/15 text-warn ring-warn/30", label: "waiting for price" },
  stale_signal: { cls: "bg-warn/15 text-warn ring-warn/30" },
  roster_stale: { cls: "bg-warn/15 text-warn ring-warn/30" },
  max_open_trades: { cls: "bg-plasma/15 text-plasma ring-plasma/30", label: "all lots open" },
  already_held: { cls: "bg-plasma/15 text-plasma ring-plasma/30", label: "already held" },
  no_consensus: { cls: "bg-raised text-ink-dim ring-line", label: "no 2nd trader" },
  insufficient_cash: { cls: "bg-plasma/15 text-plasma ring-plasma/30", label: "out of cash" },
};

function Outcome({ outcome }: { outcome: string }) {
  const o = OUTCOMES[outcome] ?? { cls: "bg-raised text-ink-dim ring-line" };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${o.cls}`}>
      {o.label ?? outcome.replaceAll("_", " ")}
    </span>
  );
}

function Side({ side }: { side: string }) {
  const buy = side === "buy";
  return (
    <span
      className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wider ${
        buy ? "bg-up text-canvas" : "bg-down text-canvas"
      }`}
    >
      {side}
    </span>
  );
}

/** One coin, with the three places to check it. */
function Token({ mint }: { mint: string }) {
  const links: [string, string, string][] = [
    ["Chart", `https://dexscreener.com/solana/${mint}`, "bg-brand-bright/15 text-brand-bright ring-brand-bright/30"],
    ["pump", `https://pump.fun/coin/${mint}`, "bg-up/15 text-up ring-up/30"],
    ["scan", `https://solscan.io/token/${mint}`, "bg-accent/15 text-accent ring-accent/30"],
  ];
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <a
        className="font-mono text-ink hover:text-accent hover:underline"
        href={`https://dexscreener.com/solana/${mint}`}
        target="_blank"
        rel="noreferrer"
        title={mint}
      >
        {short(mint)}
      </a>
      {links.map(([label, href, cls]) => (
        <a
          key={label}
          className={`rounded-full px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider ring-1 transition hover:brightness-125 ${cls}`}
          href={href}
          target="_blank"
          rel="noreferrer"
          aria-label={`${label} for ${mint}`}
        >
          {label}
        </a>
      ))}
    </span>
  );
}

function Wallet({ wallet }: { wallet: string }) {
  return (
    <a
      className="font-mono text-ink-dim hover:text-accent hover:underline"
      href={`https://solscan.io/account/${wallet}`}
      target="_blank"
      rel="noreferrer"
      title={wallet}
    >
      {short(wallet)}
    </a>
  );
}

function Stat({ label, value, hint, cls, bar }: {
  label: string; value: string; hint?: ReactNode; cls: string; bar: string;
}) {
  return (
    <div className={`relative overflow-hidden rounded-xl border border-line bg-gradient-to-br ${bar} p-4`}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-dim">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${cls}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-ink-dim">{hint}</div> : null}
    </div>
  );
}

/** A feed's freshness: green when recent, amber when late. */
function Light({ label, at, okMinutes }: { label: string; at?: string | null; okMinutes: number }) {
  const age = ageMinutes(at);
  const ok = age !== null && age <= okMinutes;
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-sunken/80 px-3 py-1 text-xs text-ink-dim">
      <span className={`size-2 rounded-full ${ok ? "bg-up shadow-[0_0_8px_var(--color-up)]" : "bg-warn"}`} />
      <span>{label}</span>
      <span className="font-mono text-ink">{time(at)}</span>
    </span>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <Panel>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {count !== undefined ? (
          <span className="rounded-full bg-accent/10 px-2 py-0.5 font-mono text-xs text-accent">{count}</span>
        ) : null}
      </div>
      {children}
    </Panel>
  );
}

function Lots({ positions }: { positions: Position[] }) {
  return (
    <>
      <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                  <tr>
                    <th className="py-2">Token</th>
                    <th>Trader</th>
                    <th>Status</th>
                    <th className="text-right">Spent</th>
                    <th className="text-right">Value / proceeds</th>
                    <th className="text-right">P/L</th>
                    <th className="pl-4">Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={pos.id} className="border-t border-line/70 transition hover:bg-raised">
                      <td className="py-2.5"><Token mint={pos.mint} /></td>
                      <td><Wallet wallet={pos.wallet} /></td>
                      <td>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
                          pos.status === "open" ? "bg-plasma/15 text-plasma ring-plasma/30" : "bg-raised text-ink-dim ring-line"
                        }`}>
                          {pos.status}
                        </span>
                      </td>
                      <td className="text-right font-mono tabular-nums">{usd(pos.spent_usd)}</td>
                      <td className="text-right font-mono tabular-nums">{usd(pos.value_usd)}</td>
                      <td className={`text-right font-mono font-semibold tabular-nums ${tone(pos.pnl_usd)}`}>{usd(pos.pnl_usd, true)}</td>
                      <td className="pl-4 text-ink-dim">{time(pos.opened_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!positions.length && (
              <p className="text-sm text-ink-dim">No copied trades yet.</p>
            )}
    </>
  );
}

/** The second book: buys only what another followed trader bought in the hour before. */
function ConsensusBook({ c, maxLots, trade }: { c: Consensus; maxLots: number; trade: string }) {
  const skipped = Object.entries(c.decisions).filter(([k]) => k !== "opened");
  return (
    <Section title="Multiple-traders book" count={c.positions.length}>
      <p className="mb-3 text-sm text-ink-dim">
        A second $500 paper book on the same traders. It buys only when a different followed
        trader bought the same coin in the hour before, then sells when the trader it copied
        sells. Started {time(c.started_at)}. {usd(trade)} a lot, up to {maxLots} at once.
      </p>
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Equity" value={usd(c.equity_usd)} cls="text-ink" bar="from-accent/15 to-transparent" />
        <Stat label="P/L" value={usd(c.pnl_usd, true)} cls={tone(c.pnl_usd)}
              bar={Number(c.pnl_usd) < 0 ? "from-down/15 to-transparent" : "from-up/15 to-transparent"} />
        <Stat label="Cash" value={usd(c.cash_usd)} cls="text-brand-bright" bar="from-brand-bright/15 to-transparent" />
        <Stat label="Open lots" value={`${c.open_trades} / ${maxLots}`} cls="text-plasma" bar="from-plasma/15 to-transparent"
              hint={`${c.decisions.opened ?? 0} copied${skipped.length ? " · " : ""}${skipped
                .map(([k, n]) => `${n} ${OUTCOMES[k]?.label ?? k.replaceAll("_", " ")}`).join(" · ")}`} />
      </div>
      <Lots positions={c.positions} />
    </Section>
  );
}

const MEDALS = ["bg-warn text-canvas", "bg-ink-2 text-canvas", "bg-down text-canvas"];

export function FomoLabPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["fomo-lab", "board"],
    queryFn: () => api.get<Board>("/labs/fomo/board"),
    refetchInterval: 30_000,
  });
  const open = data?.open_trades ?? 0;
  const maxLots = data?.max_open_trades ?? 20;

  return (
    <div className="space-y-5 pb-12">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface bg-gradient-to-br from-plasma/25 via-surface to-brand-bright/20 p-5 sm:p-6">
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 size-56 rounded-full bg-plasma/20 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-20 left-1/3 size-56 rounded-full bg-brand-bright/20 blur-3xl" />
        <div className="relative space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-sunken/80 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-dim">
              Paper copy · research
            </span>
            {data?.running ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-up/15 px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-up ring-1 ring-up/30">
                <span className="size-1.5 animate-pulse rounded-full bg-up" />
                Live
              </span>
            ) : null}
          </div>
          <h1 className="text-4xl font-black tracking-tight text-ink sm:text-5xl">
            <span className="text-plasma">FOMO</span> Lab
          </h1>
          <p className="max-w-3xl text-sm text-ink-dim">
            One $500 paper book follows the top 20 fomo.family traders by rolling 24-hour
            P&amp;L. Each observed buy opens a $50 lot when cash and a fresh price are
            available. Each sell closes one matching lot. The roster refreshes every
            hour; swaps are checked every two minutes.
          </p>
        </div>
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
            <Stat label="Equity" value={usd(data.equity_usd)} cls="text-ink"
                  bar="from-accent/15 to-transparent" hint={`from ${usd(data.starting_usd)}`} />
            <Stat label="P/L" value={usd(data.pnl_usd, true)} cls={tone(data.pnl_usd)}
                  bar={Number(data.pnl_usd) < 0 ? "from-down/15 to-transparent" : "from-up/15 to-transparent"} />
            <Stat label="Cash" value={usd(data.cash_usd)} cls="text-brand-bright"
                  bar="from-brand-bright/15 to-transparent" hint={`${usd(data.trade_usd)} a buy`} />
            <Stat label="Open lots" value={`${open} / ${maxLots}`} cls="text-plasma"
                  bar="from-plasma/15 to-transparent"
                  hint={
                    <span className="mt-1 flex gap-1" aria-hidden>
                      {Array.from({ length: maxLots }, (_, i) => (
                        <span key={i} className={`h-1.5 flex-1 rounded-full ${i < open ? "bg-plasma" : "bg-raised"}`} />
                      ))}
                    </span>
                  } />
          </div>

          <Panel>
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-2 rounded-full border border-line bg-sunken/80 px-3 py-1 text-xs text-ink-dim">
                Started <span className="font-mono text-ink">{time(data.started_at)}</span>
              </span>
              <Light label="Roster fetched" at={data.roster_at} okMinutes={70} />
              <Light label="Source snapshot" at={data.source_captured_at} okMinutes={120} />
              <Light label="Last complete swap poll" at={data.feed_at} okMinutes={6} />
              <span className="inline-flex items-center rounded-full border border-line bg-sunken/80 px-3 py-1 text-xs text-ink-dim">
                {data.stale_marks ?? 0} stale open marks
              </span>
            </div>
            {data.feed_error && (
              <p className="mt-3 rounded-lg bg-down/10 px-3 py-2 text-sm text-danger ring-1 ring-down/30">
                Feed issue: {data.feed_error}
              </p>
            )}
            <p className="mt-3 text-sm text-ink-dim">{data.note}</p>
          </Panel>

          <Section title="Paper lots" count={data.positions?.length ?? 0}>
            <Lots positions={data.positions ?? []} />
          </Section>

          {data.consensus ? <ConsensusBook c={data.consensus} maxLots={maxLots} trade={data.trade_usd} /> : null}

          <Section title="Observed swaps and decisions" count={data.signals?.length ?? 0}>
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="sticky top-0 bg-surface text-[11px] uppercase tracking-wider text-ink-dim">
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
                      className="border-t border-line/70 transition hover:bg-raised"
                    >
                      <td className="py-2.5 text-ink-dim">{time(signal.traded_at)}</td>
                      <td><Wallet wallet={signal.wallet} /></td>
                      <td><Side side={signal.side} /></td>
                      <td><Token mint={signal.mint} /></td>
                      <td><Outcome outcome={signal.outcome} /></td>
                      <td>
                        <a
                          className="font-mono text-accent hover:underline"
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
          </Section>

          <Section title="Following now" count={data.leaders?.length ?? 0}>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {data.leaders?.map((leader) => (
                <div
                  key={leader.user_id}
                  className="flex items-center gap-3 rounded-xl border border-line bg-raised/60 p-3 transition hover:border-accent/50"
                >
                  <span
                    className={`grid size-8 shrink-0 place-items-center rounded-full font-mono text-xs font-bold ${
                      MEDALS[leader.rank - 1] ?? "bg-raised text-ink-dim"
                    }`}
                  >
                    {leader.rank}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-ink">{leader.handle}</div>
                    <div className="text-xs"><Wallet wallet={leader.wallet} /></div>
                  </div>
                  <div className={`font-mono text-sm font-semibold tabular-nums ${tone(leader.pnl_24h_usd)}`}>
                    {usd(leader.pnl_24h_usd, true)}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-ink-dim">
              24h P/L is what fomo.family reports; it does not enter the paper book.
            </p>
          </Section>
        </>
      )}
    </div>
  );
}
