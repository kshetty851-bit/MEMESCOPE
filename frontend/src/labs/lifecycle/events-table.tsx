import { Badge } from "@/components/ui/badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { InfoTip } from "@/components/ui/tooltip";
import { formatPrice, shortenAddress } from "@/lib/format";

import {
  Figure,
  MeasuredValue,
  Unavailable,
  agoFromIso,
  formatRatioPct,
  formatUtc,
  humanize,
} from "./display";
import type { MemeEvent } from "./types";

/** "5m" < "15m" < "1h" < "24h" — order horizons by duration, not by string. */
export function horizonSeconds(key: string): number {
  const m = /^(\d+(?:\.\d+)?)\s*(s|m|h|d)$/i.exec(key.trim());
  if (!m) return Number.MAX_SAFE_INTEGER;
  const unit = { s: 1, m: 60, h: 3600, d: 86_400 }[m[2]!.toLowerCase() as "s" | "m" | "h" | "d"];
  return Number(m[1]) * unit;
}

export function EventsTable({ events }: { events: MemeEvent[] }) {
  const horizons = Array.from(new Set(events.flatMap((e) => Object.keys(e.returns)))).sort(
    (a, b) => horizonSeconds(a) - horizonSeconds(b),
  );

  const columns: Column<MemeEvent>[] = [
    {
      key: "type",
      header: "Event",
      cell: (e) => (
        <span className="flex flex-col items-start gap-1">
          <span className="font-medium text-ink">{humanize(e.event_type)}</span>
          {e.contains_backfill || e.mode === "exploratory" ? (
            <Badge tone="warn">EXPLORATORY (backfill)</Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "detected",
      header: "Detected at",
      cell: (e) => (
        <span className="flex flex-col leading-tight" data-numeric>
          <span>{formatUtc(e.detected_at)}</span>
          <span className="text-xs text-ink-3">{agoFromIso(e.detected_at)}</span>
        </span>
      ),
    },
    {
      key: "token",
      header: "Token",
      cell: (e) => (
        <span data-numeric className="text-xs text-ink-2">
          {e.mint ? shortenAddress(e.mint) : "—"}
        </span>
      ),
    },
    {
      key: "divergence",
      header: "Divergence case",
      cell: (e) =>
        e.divergence_case ? (
          <span className="text-ink-2">{humanize(e.divergence_case)}</span>
        ) : (
          <Unavailable reason="no divergence case classified" />
        ),
    },
    {
      key: "state",
      header: "State",
      cell: (e) =>
        e.lifecycle_state ? (
          <Badge tone="neutral">{humanize(e.lifecycle_state)}</Badge>
        ) : (
          <Unavailable reason="state not classified" />
        ),
    },
    {
      key: "price",
      header: "Price at detection",
      align: "right",
      cell: (e) => (
        <Figure value={e.price_at_detection} format={formatPrice} reason="no price at detection" />
      ),
    },
    {
      key: "runup",
      header: (
        <span className="inline-flex items-center gap-1">
          Run-up before detection
          <InfoTip
            label="Run-up before detection"
            content="How far price had already moved by the time the event was detected. Large means the market was ahead of the signal; this is the was-it-early-enough view."
          />
        </span>
      ),
      align: "right",
      cell: (e) => <MeasuredValue measured={e.run_up_before_detection} format={formatRatioPct} />,
    },
    ...horizons.map<Column<MemeEvent>>((h) => ({
      key: `ret-${h}`,
      header: `Return ${h}`,
      align: "right",
      cell: (e) => <MeasuredValue measured={e.returns[h]} format={formatRatioPct} />,
    })),
  ];

  return (
    <Panel density="flush">
      <PanelHeader className="mb-0 p-4 pb-3">
        <PanelTitle>Events — was it early enough?</PanelTitle>
        <p className="max-w-[48ch] text-xs text-ink-3">
          Returns are measured after detection, from the price at detection.
          Horizons not yet elapsed are unavailable, not zero.
        </p>
      </PanelHeader>
      <div className="px-2 pb-2">
        <DataTable
          caption="Detected events with returns after detection and run-up before"
          columns={columns}
          rows={events}
          getRowId={(e) => `${e.event_type}|${e.detected_at}|${e.mint ?? ""}`}
          minWidth="900px"
          stickyHeader={false}
          empty={
            <p className="px-3 py-8 text-center text-sm text-ink-3">
              No events detected for this meme.
            </p>
          }
        />
      </div>
    </Panel>
  );
}
