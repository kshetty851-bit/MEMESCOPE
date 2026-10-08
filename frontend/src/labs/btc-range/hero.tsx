"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Num } from "@/components/ui/num";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

import { CALL_LABEL, pct, signTone, usd, when } from "./format";
import type { BookOut, Call, SignalOut, StatusOut } from "./types";

const CALL_TONE: Record<Call, "safe" | "danger" | "neutral"> = {
  long: "safe",
  short: "danger",
  wait: "neutral",
};

export function CallChip({ call }: { call: Call }) {
  return (
    <Badge tone={CALL_TONE[call]} className="px-3 py-1 text-sm font-semibold">
      {CALL_LABEL[call]}
    </Badge>
  );
}

function Cell({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-testid={`hero-${id}`}
      className={cn("flex min-w-0 flex-col gap-1 bg-surface px-3 py-2.5", className)}
    >
      <span className="text-label font-medium uppercase text-ink-3">{label}</span>
      <span className="truncate text-md font-medium">{children}</span>
      {hint ? <span className="truncate text-xs text-ink-3">{hint}</span> : null}
    </div>
  );
}

/**
 * The hero strip. Left to right it reads as the chain a reader follows: the
 * price, the range it sits in, what the paper strategy calls, the three levels
 * that call carries, how sure it is, and what the book has made.
 *
 * Entry, TP and SL are `null` on WAIT and render as a dash. They are never
 * filled in from the range or the last close: a level the strategy did not
 * set is not a level.
 */
export function Hero({
  price,
  signal,
  book,
}: {
  price: StatusOut["price"];
  signal: SignalOut | null;
  book: BookOut | null;
}) {
  const range = signal?.range ?? null;
  const active = signal !== null && signal.call !== "wait";
  const metrics = book?.metrics ?? null;

  return (
    <div
      data-testid="hero"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-4 xl:grid-cols-8"
    >
      <Cell
        id="price"
        label="BTC/USDT"
        hint={
          price
            ? price.candle_closed
              ? when(price.at)
              : `forming candle · ${when(price.at)}`
            : undefined
        }
      >
        <Num value={price?.value ?? null} display={usd(price?.value)} />
      </Cell>

      <Cell
        id="range"
        label="Current range"
        hint={range ? `width ${pct(range.width_pct)}` : undefined}
      >
        {range ? (
          <span data-numeric>
            {usd(range.support, { digits: 0 })}–{usd(range.resistance, { digits: 0 })}
          </span>
        ) : (
          <Num value={null} />
        )}
      </Cell>

      <Cell
        id="call"
        label="Paper strategy call"
        hint={signal ? `as of ${when(signal.at)}` : undefined}
      >
        {signal ? (
          <CallChip call={signal.call} />
        ) : (
          <Num value={null} absentLabel="no call yet" />
        )}
      </Cell>

      <Cell id="entry" label="Entry">
        <Num value={active ? signal.entry : null} display={usd(signal?.entry)} />
      </Cell>

      <Cell
        id="tp"
        label="TP"
        hint={
          active && signal.reward_risk
            ? `R:R ${Number(signal.reward_risk).toFixed(2)}`
            : undefined
        }
      >
        <Num
          value={active ? signal.take_profit : null}
          display={usd(signal?.take_profit)}
          tone="up"
        />
      </Cell>

      <Cell id="sl" label="SL">
        <Num
          value={active ? signal.stop_loss : null}
          display={usd(signal?.stop_loss)}
          tone="down"
        />
      </Cell>

      <Cell id="confidence" label="Confidence">
        {signal ? (
          <span data-numeric>
            {signal.confidence}
            <span className="text-xs text-ink-3"> / 100</span>
          </span>
        ) : (
          <Num value={null} />
        )}
      </Cell>

      <Cell
        id="pnl"
        label="Paper P&L (net)"
        hint={metrics ? `${pct(metrics.return_pct, { signed: true })} return` : undefined}
      >
        <Num
          value={metrics?.net_pnl ?? null}
          display={usd(metrics?.net_pnl, { signed: true })}
          tone={signTone(metrics?.net_pnl)}
        />
      </Cell>
    </div>
  );
}

/** Server-rendered sentences, shown as given. No prose is composed here. */
export function ReasonsList({ signal }: { signal: SignalOut | null }) {
  return (
    <Panel density="compact" data-testid="reasons">
      <PanelHeader className="mb-3">
        <PanelTitle>Why this call</PanelTitle>
        {signal ? <CallChip call={signal.call} /> : null}
      </PanelHeader>
      {!signal ? (
        <p className="text-sm text-ink-3">No signal has been computed yet.</p>
      ) : signal.reasons.length === 0 ? (
        <p className="text-sm text-ink-3">
          The strategy recorded no reasons for this call.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-sm text-ink-2">
          {signal.reasons.map((reason) => (
            <li key={reason.code} data-code={reason.code} className="flex gap-2">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-4" />
              <span>{reason.text}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
