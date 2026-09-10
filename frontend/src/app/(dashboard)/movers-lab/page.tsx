"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AGED_BLURB, FRESH_BLURB, MatrixSection } from "@/components/lab/matrix-grid";
import { LabTradesTable } from "@/components/lab/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";

import { useMatrixBoard } from "@/hooks/use-matrix";
import { useMoversBoard, useMoversTrades } from "@/hooks/use-movers";
import type { MoversWallet } from "@/types/movers";

/**
 * THE MOVERS LAB — does high turnover mark a coin before it runs?
 *
 * Two $100 wallets differing in exactly one condition. The layout puts them
 * SIDE BY SIDE and never ranks them: the comparison is the finding, and a page
 * that sorted by equity would let a reader take today's position for a result.
 *
 * The disclosure sits above the numbers and is not collapsible, because the
 * measurement behind this lab is easy to overstate. "Doubled" in that research
 * meant the price touched 2x at some later moment, which no seller
 * necessarily got — and turnover behaved as a floor rather than a score, so
 * nothing here ranks or sizes by it.
 */

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

/** How long this tournament has been running, ticking live.
 *
 *  Rendered only after mount and from a state clock rather than `Date.now()`
 *  during render: the server would otherwise produce one elapsed time, the
 *  client another a moment later, and React would report a hydration
 *  mismatch on a value that is correct in both.
 */
function RunningFor({ since }: { since: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (now === null) return null;
  const started = Date.parse(since);
  if (!Number.isFinite(started)) return null;

  const secs = Math.max(0, Math.floor((now - started) / 1000));
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s_ = secs % 60;
  const pad = (n: number) => String(n).padStart(2, "0");

  return (
    <span className="font-mono text-ink" title={`Started ${since}`}>
      {d > 0 ? `${d}d ` : ""}
      {pad(h)}:{pad(m)}:{pad(s_)}
    </span>
  );
}

function WalletCard({ w, starting }: { w: MoversWallet; starting: number }) {
  const control = w.strategy_id === "MOV-04";
  return (
    <Panel density="compact">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{w.name}</Label>
        <span
          className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase ${
            control
              ? "border-line-control text-ink-3"
              : "border-accent/40 bg-accent/10 text-accent"
          }`}
        >
          {control ? "Control" : "Gated"}
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase text-muted">Equity</div>
          <div className={`font-mono text-lg ${tone(w.equity, starting)}`}>
            {money(w.equity)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Realised</div>
          <div className={`font-mono text-lg ${tone(w.realised_pnl, 0)}`}>
            {money(w.realised_pnl)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Open</div>
          <div className="font-mono text-lg text-ink">{w.open_positions}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Closed</div>
          <div className="font-mono text-lg text-ink">{w.closed_positions}</div>
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-ink-3">{w.hypothesis}</p>

      {w.entry_text.length > 0 ? (
        <ul className="mt-2 space-y-0.5">
          {w.entry_text.map((line) => (
            <li key={line} className="font-mono text-[10px] text-muted">
              · {line}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/**
 * THE OTHER TWENTY-FOUR. The Matrix Lab's two sections, shown here beneath the
 * movers arms because the operator asked to see every strategy in one place.
 * Picking a cell opens that arm's trades on the Matrix Lab page; this page's
 * own trade list stays the movers' list.
 */
function MatrixSections() {
  const router = useRouter();
  const { data, isLoading, isError } = useMatrixBoard();
  const starting = Number(data?.starting_equity ?? 100);
  const fresh = (data?.wallets ?? []).filter((w) => w.section === "FRESH");
  const aged = (data?.wallets ?? []).filter((w) => w.section === "AGED");

  if (isLoading || isError || !data?.activated) {
    return (
      <Panel density="compact">
        <Label>MATRIX LAB</Label>
        <p className="mt-2 text-xs text-muted">
          {isLoading
            ? "Loading…"
            : isError
              ? "The matrix board could not be read."
              : `The registry exists (${data?.spec_version ?? "?"}) but no tournament has been opened.`}
        </p>
      </Panel>
    );
  }
  const open = (id: string) => router.push(`/matrix-lab#${id}`);
  return (
    <>
      <MatrixSection
        title="MATRIX · FRESH — pump.fun launches"
        blurb={FRESH_BLURB}
        wallets={fresh}
        starting={starting}
        selected={null}
        onSelect={open}
      />
      <MatrixSection
        title={`MATRIX · AGED — established markets, at least ${data.min_age_hours ?? "24"}h old`}
        blurb={AGED_BLURB}
        wallets={aged}
        starting={starting}
        selected={null}
        onSelect={open}
      />
    </>
  );
}

export default function MoversLabPage() {
  const { data, isLoading, isError } = useMoversBoard();
  const trades = useMoversTrades();
  const starting = Number(data?.starting_equity ?? 100);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Movers Lab"
        title="Does the security check keep us out of the rugs?"
        description="Three $100 movers wallets and, beneath them, the Matrix Lab's twenty-four. Three $100 wallets started together, one percent of the balance per position and a hundred at a time, each held 30 minutes with no take-profit and no stop. They differ in one condition: one only buys coins the security evaluator has positively verified. In the previous run every loss was a coin going to zero. Nothing is real money."
      />

      {/* Above the numbers, and deliberately not collapsible. */}
      <Panel density="compact">
        <Label>WHAT THIS CAN AND CANNOT SHOW</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "Research simulation. Two virtual $100 wallets differing in one condition. No real order was ever placed."}
        </p>
      </Panel>

      {isLoading ? (
        <Panel density="compact">
          <p className="text-xs text-muted">Loading…</p>
        </Panel>
      ) : isError || !data ? (
        <Panel density="compact">
          <Label>NOT AVAILABLE</Label>
          <p className="mt-2 text-xs text-down">
            The board could not be read. This says nothing about the experiment —
            only that this page could not reach it.
          </p>
        </Panel>
      ) : !data.activated ? (
        <Panel density="compact">
          <Label>NOT ACTIVATED</Label>
          <p className="mt-2 text-xs text-muted">
            The registry exists ({data.spec_version}) but no tournament has been
            opened, so neither wallet is trading yet.
          </p>
        </Panel>
      ) : (
        <>
          <Panel density="compact">
            <Label>THE RULE</Label>
            <p className="mt-2 text-xs text-muted">
              Security VERIFIED required (gated arm) · liquidity at least{" "}
              <span className="font-mono text-ink">
                {money(data.min_liquidity_usd)}
              </span>{" "}
              · hold{" "}
              <span className="font-mono text-ink">
                {data.hold_minutes ?? 30} min
              </span>{" "}
              · no take-profit, no stop
              {data.valid_from ? (
                <>
                  {" "}
                  · running for <RunningFor since={data.valid_from} />
                </>
              ) : null}
            </p>
          </Panel>

          {/* One wallet. The grid survives so a second arm would sit beside
              it rather than under it if the comparison is ever restored. */}
          <div className="grid gap-4 lg:grid-cols-2">
            {data.wallets.map((w) => (
              <WalletCard key={w.strategy_id} w={w} starting={starting} />
            ))}
          </div>

          {/* The Matrix Lab's twenty-four arms, in their two sections — above
              the trade list, because on a phone anything below forty rows of
              trades is a section nobody reaches. */}
          <MatrixSections />

          {trades.data ? (
            <LabTradesTable trades={trades.data.trades} />
          ) : (
            <Panel density="compact">
              <Label>TRADES</Label>
              <p className="mt-2 text-xs text-muted">
                {trades.isError ? "The trade list could not be read." : "Loading…"}
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
