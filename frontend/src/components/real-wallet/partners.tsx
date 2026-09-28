/**
 * KARTHIK & RAFIQ, 50-50 (Karthik, 2026-09-28): what each of them has made on
 * the real wallet since 3 PM Dubai on 28 Sep, when they put in $50 each, and
 * each day's % of the balance it opened with — like Karthik's Lab.
 * Trading profit only; the server's `partners` block (`real_wallet/partners.py`).
 */

export interface PartnersDay {
  n: number;
  from: string;
  to: string;
  running: boolean;
  trades: number;
  pnl_usd: string;
  pct: string;
  balance_usd: string;
}

export interface Partners {
  started_at: string;
  capital_usd: string;
  profit_usd: string;
  balance_usd: string;
  pct: string;
  trades: number;
  wins: number;
  open: number;
  partners: { name: string; share: string; put_in_usd: string; profit_usd: string; now_usd: string }[];
  days: PartnersDay[];
}

const money = (value: string | number) => {
  const n = Number(value);
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
};
const signed = (value: string | number) => `${Number(value) >= 0 ? "+" : ""}${money(value)}`;
const tone = (value: string | number) =>
  Number(value) > 0 ? "text-up" : Number(value) < 0 ? "text-down" : "text-ink";

export function PartnersCard({ data }: { data: Partners | undefined }) {
  if (!data) return null;
  const since = new Date(data.started_at)
    .toLocaleString("en-GB", {
      timeZone: "Asia/Dubai", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
      hour12: true,
    })
    .replace("Sept", "Sep")
    .replace(/\s?(am|pm)$/i, (m) => ` ${m.trim().toUpperCase()}`);
  return (
    <section className="mt-6 rounded-lg border border-accent/40 bg-accent/[0.04] p-4" data-testid="partners">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-accent">Karthik &amp; Rafiq · 50-50</p>
        <p className="text-xs text-ink-3">
          {money(data.capital_usd)} in since {since} (Dubai) · {data.trades} trades · {data.wins} won
          {data.open ? ` · ${data.open} open` : ""}
        </p>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {data.partners.map((p) => (
          <div key={p.name} className="rounded-md border border-line bg-canvas/40 p-3">
            <p className="text-sm font-medium text-ink">{p.name}</p>
            <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone(p.profit_usd)}`}>
              {signed(p.profit_usd)}
            </p>
            <p className="text-xs text-ink-3">
              put in {money(p.put_in_usd)} · now {money(p.now_usd)}
            </p>
          </div>
        ))}
        <div className="rounded-md border border-line bg-canvas/40 p-3">
          <p className="text-sm font-medium text-ink">Together</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone(data.profit_usd)}`}>
            {signed(data.profit_usd)}
          </p>
          <p className="text-xs text-ink-3">
            {money(data.capital_usd)} → {money(data.balance_usd)} ·{" "}
            <span className={tone(data.pct)}>
              {Number(data.pct) >= 0 ? "+" : ""}
              {Number(data.pct).toFixed(2)}%
            </span>
          </p>
        </div>
      </div>

      {data.days.length ? (
        <div className="-mx-1 mt-3 flex gap-2 overflow-x-auto px-1 pb-1">
          {data.days.map((d) => (
            <div
              key={d.n}
              className={`min-w-[112px] shrink-0 rounded-lg border p-2 ${
                d.running ? "border-dashed border-line" : "border-line"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wider text-ink-3">
                {d.running ? `Day ${d.n} · so far` : `Day ${d.n}`}
              </div>
              <div className={`mt-0.5 text-base font-semibold tabular-nums ${tone(d.pct)}`}>
                {Number(d.pct) >= 0 ? "+" : ""}
                {Number(d.pct).toFixed(2)}%
              </div>
              <div className="text-[11px] tabular-nums text-ink-3">
                {signed(d.pnl_usd)} · {d.trades} trades
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <p className="mt-2 text-[11px] text-ink-3">
        Trading profit on closed trades, split half and half. SOL&apos;s own price moving is not
        counted. Each day runs 3 PM to 3 PM Dubai; its % is of the balance it opened with.
      </p>
    </section>
  );
}
