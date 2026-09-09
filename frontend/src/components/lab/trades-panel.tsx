"use client";

import { Label, Panel } from "@/components/ui/panel";
import type { LabTrade } from "@/types/lab";

/**
 * EVERY TRADE A LAB HAS MADE, each with its own P&L.
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

/** Which arm a row belongs to. Both arms buy the SAME mints at the same
 *  instant, so without this column the record reads as every token duplicated
 *  for no visible reason.
 *
 *  Labelled by STAKE (`GRAD-S2` -> `$2`), because the arms now share a clock
 *  and differ only in how the book is divided — the hold would label them
 *  identically. Falls back to the raw id rather than going blank, which is how
 *  the previous version failed silently when the ids changed shape. */
function arm(t: LabTrade): string {
  const m = /-S(\d+)$/.exec(t.strategy_id ?? "");
  return m?.[1] ? `$${Number(m[1])}` : (t.strategy_id ?? "—");
}

/** Where the coin sits now, against our entry. Closed rows only — for an open
 *  position the P&L column already IS the current mark, and repeating it in a
 *  second column would read as corroboration from a second source. */
/** What the stake would be worth now if it had never been sold. Closed rows
 *  only: for an open position the Value column already is that number. */
function IfHeldCell({ t }: { t: LabTrade }) {
  if (t.status !== "closed") return <td className="py-1.5 pr-3" />;
  const held = t.value_if_held_usd;
  if (held === null || held === undefined) {
    return <td className="py-1.5 pr-3 text-right font-mono text-muted">—</td>;
  }
  const got = Number(t.exit_proceeds_usd ?? 0);
  const stale = (t.price_now_age_minutes ?? 0) > 30;
  return (
    <td
      className={`py-1.5 pr-3 text-right font-mono ${
        stale ? "text-muted" : tone(Number(held) - got)
      }`}
      title={
        stale
          ? `Last priced ${t.price_now_age_minutes} min ago — probably dead`
          : "Gross value of the stake if never sold. Not comparable pound-for-pound with what we got, which has fees and impact removed."
      }
    >
      {money(held)}
    </td>
  );
}

function NowCell({ t }: { t: LabTrade }) {
  if (t.status !== "closed") return <td className="py-1.5 pr-3" />;
  const v = t.pct_since_entry_now;
  if (v === null || v === undefined) {
    return <td className="py-1.5 pr-3 text-right font-mono text-muted">—</td>;
  }
  // How long ago we sold. Without it the Now figure is unreadable: a coin
  // 30 points above our exit seven minutes later and one that took a day to
  // get there are completely different facts about the exit rule.
  const soldMinsAgo = t.closed_at
    ? Math.max(0, Math.round((Date.now() - Date.parse(t.closed_at)) / 60000))
    : null;
  const ago =
    soldMinsAgo === null ? null
      : soldMinsAgo < 60 ? `${soldMinsAgo}m`
      : soldMinsAgo < 1440 ? `${Math.floor(soldMinsAgo / 60)}h`
      : `${Math.floor(soldMinsAgo / 1440)}d`;

  // A mark nobody has refreshed in half an hour is a dead coin, not a price.
  // Shown greyed with an age rather than hidden: "we cannot see it" and "it
  // went nowhere" are different facts and the row should not conflate them.
  const stale = (t.price_now_age_minutes ?? 0) > 30;
  return (
    <td
      className={`py-1.5 pr-3 text-right font-mono ${stale ? "text-muted" : tone(v)}`}
      title={
        stale
          ? `Last priced ${t.price_now_age_minutes} min ago — probably dead`
          : "Gross move from our entry to the latest mark. Not what a later sale would have returned."
      }
    >
      {pct(v)}
      {stale ? <span className="ml-0.5 text-[9px]">·stale</span> : null}
      {ago ? <span className="ml-1 text-[9px] text-muted">{ago} on</span> : null}
    </td>
  );
}

function Row({ t }: { t: LabTrade }) {
  const p = pnlOf(t);
  return (
    <tr className="border-t border-line align-top">
      <td className="whitespace-nowrap py-1.5 pr-3 font-mono text-[10px] text-ink-3">{arm(t)}</td>
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
      <IfHeldCell t={t} />
      <NowCell t={t} />
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
            <th className="pb-1 pr-3 text-left font-normal">Arm</th>
            <th className="pb-1 pr-3 text-left font-normal">Mint</th>
            <th className="pb-1 pr-3 text-left font-normal">Sym</th>
            <th className="pb-1 pr-3 text-left font-normal">Opened</th>
            <th className="pb-1 pr-3 text-left font-normal">Closed</th>
            <th className="pb-1 pr-3 text-right font-normal">Held</th>
            <th className="pb-1 pr-3 text-right font-normal">Stake</th>
            <th className="pb-1 pr-3 text-right font-normal">Value</th>
            <th className="pb-1 pr-3 text-right font-normal">P&amp;L</th>
            <th className="pb-1 pr-3 text-right font-normal">P&amp;L %</th>
            <th
              className="pb-1 pr-3 text-right font-normal"
              title="What the stake would be worth now if it had never been sold. Gross: selling it would cost fees and impact, which the Value column already has removed."
            >
              If held
            </th>
            <th
              className="pb-1 pr-3 text-right font-normal"
              title="Gross move from our entry to the latest mark, and how long since we sold. Compare it against the P&L % beside it: the difference is what holding would have added or cost. Raw price, not a sellable value."
            >
              Now
            </th>
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
export function LabTradesTable({ trades }: { trades: LabTrade[] }) {
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
