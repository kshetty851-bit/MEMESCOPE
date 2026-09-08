"use client";

import { Label, Panel } from "@/components/ui/panel";
import { useFiveMinTrades } from "@/hooks/use-fivemin";
import type { LabTrade } from "@/types/lab";

/**
 * EVERY TRADE THE FIVE-MINUTE LAB HAS MADE, each with its own P&L.
 *
 * The board's `positions` is a display window — the most recent few — and it
 * shows a multiple, not money. This is the record: open and closed, oldest to
 * newest within each, the full mint so a reader can check any row against the
 * market themselves, and the profit or loss of every row in dollars and as a
 * percent of what was staked.
 *
 * An open row's P&L is what the position could be SOLD for minus its cost —
 * impact and fees included — so a freshly opened trade shows a small loss.
 * That is the truth of it, not a rendering bug.
 */

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function tone(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > 0 ? "text-up" : Number(v) < 0 ? "text-down" : "text-ink";
}

function when(iso: string | null): string {
  return iso ? iso.slice(5, 16).replace("T", " ") : "—";
}

/** P&L of one row: realised once closed, otherwise sellable value minus cost. */
export function pnlOf(t: LabTrade): number | null {
  const v = t.status === "closed" ? t.realised_pnl : t.unrealised_pnl;
  return v === null || v === undefined ? null : Number(v);
}

export function pnlPctOf(t: LabTrade): number | null {
  const p = pnlOf(t);
  const size = Number(t.size_usd);
  return p === null || !Number.isFinite(size) || size === 0 ? null : (p / size) * 100;
}

function sum(rows: LabTrade[]): number {
  return rows.reduce((acc, t) => acc + (pnlOf(t) ?? 0), 0);
}

function Row({ t }: { t: LabTrade }) {
  const p = pnlOf(t);
  return (
    <tr className="border-t border-line align-top">
      <td className="break-all py-1.5 pr-3 font-mono text-[10px] text-ink">{t.mint}</td>
      <td className="py-1.5 pr-3 font-mono text-[10px] text-muted">{t.symbol ?? "—"}</td>
      <td className="whitespace-nowrap py-1.5 pr-3 font-mono text-[10px] text-muted">
        {when(t.opened_at)}
      </td>
      <td className="whitespace-nowrap py-1.5 pr-3 font-mono text-[10px] text-muted">
        {when(t.closed_at)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">
        {(Number(t.held_hours) * 60).toFixed(1)}m
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{money(t.size_usd)}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">
        {money(t.status === "closed" ? t.exit_proceeds_usd : t.current_value_usd)}
      </td>
      <td className={`py-1.5 pr-3 text-right font-mono ${tone(p)}`}>{money(p)}</td>
      <td className={`py-1.5 pr-3 text-right font-mono ${tone(p)}`}>{pct(pnlPctOf(t))}</td>
      <td className="py-1.5 font-mono text-[10px] text-muted">
        {t.status === "open" ? "open" : (t.exit_reason ?? "closed")}
      </td>
    </tr>
  );
}

function Table({ rows }: { rows: LabTrade[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="mt-2 w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase text-muted">
            <th className="pb-1 pr-3 text-left font-normal">Mint</th>
            <th className="pb-1 pr-3 text-left font-normal">Sym</th>
            <th className="pb-1 pr-3 text-left font-normal">Opened</th>
            <th className="pb-1 pr-3 text-left font-normal">Closed</th>
            <th className="pb-1 pr-3 text-right font-normal">Held</th>
            <th className="pb-1 pr-3 text-right font-normal">Stake</th>
            <th className="pb-1 pr-3 text-right font-normal">Value</th>
            <th className="pb-1 pr-3 text-right font-normal">P&amp;L</th>
            <th className="pb-1 pr-3 text-right font-normal">P&amp;L %</th>
            <th className="pb-1 text-left font-normal">Exit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <Row key={t.id} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Pure: renders whatever it is handed. The container below fetches. */
export function FiveMinTradesTable({ trades }: { trades: LabTrade[] }) {
  // Oldest first within each group: a record reads forward.
  const byOpen = (a: LabTrade, b: LabTrade) => a.opened_at.localeCompare(b.opened_at);
  const open = trades.filter((t) => t.status === "open").sort(byOpen);
  const closed = trades.filter((t) => t.status === "closed").sort(byOpen);
  const wins = closed.filter((t) => (pnlOf(t) ?? 0) > 0).length;
  const unrealised = sum(open);
  const realised = sum(closed);

  return (
    <>
      <Panel density="compact">
        <Label>OPEN — {open.length}</Label>
        <p className={`mt-1 text-[11px] ${tone(unrealised)}`}>
          Unrealised {money(unrealised)} · shown at what the book could be sold for, not what
          it cost
        </p>
        {open.length === 0 ? (
          <p className="mt-2 text-xs text-muted">Nothing open.</p>
        ) : (
          <Table rows={open} />
        )}
      </Panel>
      <Panel density="compact">
        <Label>CLOSED — {closed.length}</Label>
        <p className={`mt-1 text-[11px] ${tone(realised)}`}>
          Realised {money(realised)} · {wins} of {closed.length} closed above cost
        </p>
        {closed.length === 0 ? (
          <p className="mt-2 text-xs text-muted">Nothing closed yet.</p>
        ) : (
          <Table rows={closed} />
        )}
      </Panel>
    </>
  );
}

export function FiveMinTradesPanel() {
  const { data, isLoading, isError } = useFiveMinTrades();
  if (isLoading) {
    return (
      <Panel density="compact">
        <Label>TRADES</Label>
        <p className="mt-2 text-xs text-muted">Loading…</p>
      </Panel>
    );
  }
  if (isError || !data) {
    // Visible on purpose: a panel that vanishes on error reads as "no trades".
    return (
      <Panel density="compact">
        <Label>TRADES</Label>
        <p className="mt-2 text-xs text-down">The trade list could not be read.</p>
      </Panel>
    );
  }
  return <FiveMinTradesTable trades={data.trades} />;
}
