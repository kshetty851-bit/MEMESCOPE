"use client";

import type { ReactNode } from "react";

import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  dexscreener,
  duration,
  pct,
  signedUsd,
  TONE_CLASS,
  tone,
  usd,
} from "@/labs/rafiq/format";

import {
  type Rafiqv2Book,
  useRafiqv2Positions,
  useRafiqv2Status,
  useRafiqv2Trades,
} from "./api";

/**
 * RAFIQV2 LAB — six books, one engine, each learning from its own trades.
 *
 * Paper only. Every number is served computed; this page only draws it. The
 * rules shown are the books' own JSON, as the server read them.
 */

const EXIT_LABELS: Record<string, string> = {
  stop: "Stop",
  profit_lock: "Profit lock",
  runner_trail: "Runner trail",
  max_hold: "Max hold",
  pool_gone: "Pool gone",
  rug_30s: "Rug 30s",
  rug_60s: "Rug 60s",
  rug_120s: "Rug 2m",
  abandon_10m: "Abandon 10m",
  abandon_20m: "Abandon 20m",
};

const mult = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Number(v).toFixed(3)}x`;

/** Seconds matter here: the rug ladder's first rungs are at 30s and 60s. */
const secs = (s: number) => (s < 60 ? `${Math.max(0, Math.round(s))}s` : duration(s));

const dollars = (n: number) => `$${n.toLocaleString("en-US")}`;

function Stat({
  label,
  value,
  toneKey,
}: {
  label: string;
  value: string;
  toneKey?: "up" | "down" | "flat";
}) {
  return (
    <div>
      <p className="text-label uppercase text-ink-4">{label}</p>
      <p
        className={`font-mono text-sm tabular-nums ${toneKey ? TONE_CLASS[toneKey] : "text-ink"}`}
      >
        {value}
      </p>
    </div>
  );
}

function Token({ mint, symbol }: { mint: string; symbol: string | null }) {
  return (
    <a
      href={dexscreener(mint)}
      target="_blank"
      rel="noopener noreferrer"
      title={mint}
      className="text-ink underline decoration-line underline-offset-2 hover:text-accent"
    >
      {symbol ?? `${mint.slice(0, 6)}…`}
    </a>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="-mx-3 overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <thead className="border-y border-line text-label uppercase text-ink-4">
          <tr>
            {head.map((h, i) => (
              <th
                key={h}
                className={`p-2 font-medium ${i < 2 ? "text-left" : "text-right"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

const cell = "p-2 text-right font-mono tabular-nums";

function BookCard({ book }: { book: Rafiqv2Book }) {
  const ret =
    book.equity === null
      ? null
      : String((Number(book.equity) / Number(book.starting_equity) - 1) * 100);
  const lrn = book.learning;
  return (
    <Panel density="compact">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="font-mono text-sm text-accent">{book.code}</span>
          <span className="truncate text-sm text-ink">{book.name}</span>
        </div>
        {book.halted.length > 0 ? (
          <span className="rounded bg-raised px-1.5 py-0.5 text-label uppercase text-warn">
            Halted
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-ink-3">{book.identity}</p>

      <div className="mt-2 flex items-baseline gap-2">
        <p className="font-mono text-lg tabular-nums text-ink">{usd(book.equity)}</p>
        <p className={`font-mono text-xs tabular-nums ${TONE_CLASS[tone(ret)]}`}>
          {pct(ret)}
        </p>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 border-t border-line pt-2">
        <Stat label="Open" value={String(book.open_positions)} />
        <Stat
          label="Closed"
          value={`${book.closed_trades} (${book.wins}W/${book.losses}L)`}
        />
        <Stat
          label="Per trade"
          value={signedUsd(book.mean_net_per_trade)}
          toneKey={tone(book.mean_net_per_trade)}
        />
        <Stat
          label="Realised"
          value={signedUsd(book.realised_pnl)}
          toneKey={tone(book.realised_pnl)}
        />
        <Stat
          label="Unrealised"
          value={signedUsd(book.unrealised_pnl)}
          toneKey={tone(book.unrealised_pnl)}
        />
        <Stat label="Ratchet floor" value={usd(book.ratchet_floor)} />
      </div>

      {lrn ? (
        <div className="mt-2 border-t border-line pt-2 text-xs text-ink-3">
          <p>
            <span className="text-label uppercase text-ink-4">Learned </span>
            rug strictness{" "}
            <span className="font-mono text-ink-2">
              {lrn.rug_strictness >= 0 ? "+" : ""}
              {lrn.rug_strictness.toFixed(2)}
            </span>
            {" · "}lock give-back{" "}
            <span className="font-mono text-ink-2">{lrn.lock_giveback.toFixed(2)}</span>
            {" · "}size <span className="font-mono text-ink-2">×{lrn.size_multiplier}</span>
          </p>
          <p className="mt-0.5">
            {lrn.regime_note}; {lrn.closes_learned} closes heard,{" "}
            {lrn.closes_awaiting_their_hour} waiting out their hour. {book.window_deaths} of
            the last {book.window_trades} tokens died.
          </p>
        </div>
      ) : null}

      {book.halted.map((h) => (
        <p key={h} className="mt-2 border-t border-line pt-2 text-xs text-warn">
          {h}
        </p>
      ))}
    </Panel>
  );
}

function Rules({ books }: { books: Rafiqv2Book[] }) {
  const shared = books[0]?.rules;
  if (!shared) return null;
  const { fast_rug_gates: rug, profit_lock: lock } = shared;
  return (
    <Panel density="compact">
      <PanelHeader>
        <PanelTitle>How every book trades</PanelTitle>
      </PanelHeader>
      <div className="mt-2 grid gap-4 lg:grid-cols-3 text-xs text-ink-2">
        <div>
          <p className="text-label uppercase text-ink-4">
            Rug ladder — the latest checkpoint governs
          </p>
          <ul className="mt-1 space-y-0.5">
            {rug.ladder.map((r) => (
              <li key={r.label}>
                after <span className="font-mono">{secs(r.after_seconds)}</span>, sold
                unless at least <span className="font-mono">{mult(r.min_multiple)}</span>{" "}
                entry
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-label uppercase text-ink-4">
            Profit lock — the floor never falls
          </p>
          <ul className="mt-1 space-y-0.5">
            {lock.ladder.map((r) => (
              <li key={r.once_peak_reaches_pct}>
                once the peak touches{" "}
                <span className="font-mono">+{r.once_peak_reaches_pct}%</span>, never sold
                below <span className="font-mono">+{r.never_sell_below_pct}%</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-1">
          <p className="text-label uppercase text-ink-4">Sells, checked in this order</p>
          <p>
            stop → profit lock → scale-out → runner trail (
            {shared.exits.runner_trail_frac * 100}% off the peak) → rug ladder → max hold. A
            pool that reads gone is worth nothing at once, and is booked at nothing once it
            has read gone for 10 minutes.
          </p>
          <p className="text-label uppercase text-ink-4">
            Halts new entries (never force-sells)
          </p>
          <p>
            A {shared.death_rate_breaker.halt_for_hours}h pause once{" "}
            {shared.death_rate_breaker.halt_at_death_rate_pct}% of the last{" "}
            {shared.death_rate_breaker.window} closed tokens died (judged from{" "}
            {shared.death_rate_breaker.min_sample}); a stop while equity is{" "}
            {shared.equity_ratchet.give_back_pct}% under its high; and a stop for the rest
            of a day that has lost {shared.daily_breaker.max_daily_drawdown_pct}%.
          </p>
        </div>
      </div>
      <Table
        head={[
          "Book",
          "Name",
          "Min liquidity",
          "Min cap",
          "Score",
          "Stop",
          "Box",
          "Scale-out",
        ]}
      >
        {books.map(({ code, name, rules: r }) => (
          <tr key={code} className="border-b border-line">
            <td className="p-2 font-mono text-accent">{code}</td>
            <td className="p-2 text-ink-2">{name}</td>
            <td className={cell}>{dollars(r.entry_gate.min_liquidity_usd)}</td>
            <td className={cell}>{dollars(r.entry_gate.min_market_cap_usd)}</td>
            <td className={cell}>{r.entry_score_min}</td>
            <td className={cell}>{mult(r.exits.stop)}</td>
            <td className={cell}>{duration(r.exits.max_hold_minutes * 60)}</td>
            <td className={cell}>
              {r.exits.scale_out
                ? `${r.exits.scale_out.sell_fraction * 100}% at ${mult(r.exits.scale_out.at_multiple)}`
                : "none"}
            </td>
          </tr>
        ))}
      </Table>
    </Panel>
  );
}

export function Rafiqv2LabPage() {
  const status = useRafiqv2Status();
  const positions = useRafiqv2Positions();
  const trades = useRafiqv2Trades();

  if (status.isPending) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (status.isError) {
    return (
      <div className="p-4">
        <ErrorState
          title="Rafiqv2 Lab is unavailable"
          body="The lab's status endpoint did not respond."
          onRetry={() => status.refetch()}
        />
      </div>
    );
  }

  const books = status.data.books;
  const log = books
    .flatMap((b) => b.adjustments.map((a) => ({ ...a, book: b.code })))
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 40);

  return (
    <div className="space-y-4 p-4">
      <Panel density="compact">
        <PanelHeader className="flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-4">
          <PanelTitle>Rafiqv2 Lab</PanelTitle>
          <Label>Research simulation — paper only, not real money</Label>
        </PanelHeader>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          Six books on one engine, each from its own $1,000. They share a rug ladder that
          cuts in seconds, a profit lock that stops a winner going red, and three breakers
          that stop new entries. Each book learns from its own closes, and only moves a
          setting after 40 closes and a z-score of at least 1.96. It learns how to exit, not
          which token to buy. Nothing in this lab has made money yet: these rules limit
          losses, they do not promise profit.
        </p>
        {status.data.running ? null : (
          <p className="mt-2 text-sm text-warn">
            Not running: RAFIQV2_LAB_ENABLED is off. The books below have not traded.
          </p>
        )}
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {books.map((b) => (
          <BookCard key={b.code} book={b} />
        ))}
      </div>

      <Rules books={books} />

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Open positions</PanelTitle>
        </PanelHeader>
        {positions.data?.length ? (
          <Table
            head={[
              "Book",
              "Token",
              "Age",
              "Now",
              "Peak",
              "Lock floor",
              "Held",
              "Value",
              "P&L",
            ]}
          >
            {positions.data.map((p) => (
              <tr key={`${p.book}-${p.mint_address}`} className="border-b border-line">
                <td className="p-2 font-mono text-accent">{p.book}</td>
                <td className="p-2">
                  <Token mint={p.mint_address} symbol={p.symbol} />
                </td>
                <td className={cell}>{secs(p.age_seconds)}</td>
                <td className={cell}>{mult(p.multiple)}</td>
                <td className={cell}>{mult(p.peak_multiple)}</td>
                <td className={cell}>{mult(p.lock_floor)}</td>
                <td className={cell}>{`${Number(p.fraction_open) * 100}%`}</td>
                <td className={cell}>{usd(p.current_value)}</td>
                <td className={`${cell} ${TONE_CLASS[tone(p.unrealised_pnl)]}`}>
                  {signedUsd(p.unrealised_pnl)}
                </td>
              </tr>
            ))}
          </Table>
        ) : (
          <EmptyState title="Nothing open" body="No book holds a position right now." />
        )}
      </Panel>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Closed trades</PanelTitle>
        </PanelHeader>
        {trades.data?.length ? (
          <Table
            head={["Book", "Token", "Held", "Exit", "Peak", "Hour after", "P&L", "Return"]}
          >
            {trades.data.map((t) => (
              <tr
                key={`${t.book}-${t.mint_address}`}
                className="border-b border-line"
                title={t.exit_evidence ?? undefined}
              >
                <td className="p-2 font-mono text-accent">{t.book}</td>
                <td className="p-2">
                  <Token mint={t.mint_address} symbol={t.symbol} />
                </td>
                <td className={cell}>{secs(t.hold_seconds)}</td>
                <td className="p-2 text-right text-ink-2">
                  {EXIT_LABELS[t.exit_reason] ?? t.exit_reason}
                  {t.scaled_out ? " (after scale-out)" : ""}
                  {t.died ? <span className="text-down"> · died</span> : null}
                </td>
                <td className={cell}>{mult(t.peak_multiple)}</td>
                <td className={cell}>{mult(t.forward_peak_multiple)}</td>
                <td className={`${cell} ${TONE_CLASS[tone(t.pnl_usd)]}`}>
                  {signedUsd(t.pnl_usd)}
                </td>
                <td className={`${cell} ${TONE_CLASS[tone(t.return_pct)]}`}>
                  {pct(t.return_pct)}
                </td>
              </tr>
            ))}
          </Table>
        ) : (
          <EmptyState
            title="No closed trades yet"
            body="A trade appears here when its last part sells."
          />
        )}
      </Panel>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>What the books changed, and when they stopped</PanelTitle>
        </PanelHeader>
        {log.length ? (
          <Table head={["Book", "Setting", "When", "From", "To", "n", "z", "Why"]}>
            {log.map((a) => (
              <tr key={`${a.book}-${a.at}-${a.parameter}`} className="border-b border-line">
                <td className="p-2 font-mono text-accent">{a.book}</td>
                <td className="p-2 text-ink-2">{a.parameter.replace(/_/g, " ")}</td>
                <td className={cell}>{new Date(a.at).toLocaleString()}</td>
                <td className={cell}>{Number(a.old_value).toFixed(3)}</td>
                <td className={cell}>{Number(a.new_value).toFixed(3)}</td>
                <td className={cell}>{a.sample_size ?? "—"}</td>
                <td className={cell}>{a.z_score ?? "—"}</td>
                <td className="p-2 text-xs text-ink-3">{a.reason}</td>
              </tr>
            ))}
          </Table>
        ) : (
          <EmptyState
            title="Nothing changed yet"
            body="A setting moves only after 40 closes and a z-score of at least 1.96."
          />
        )}
      </Panel>
    </div>
  );
}
