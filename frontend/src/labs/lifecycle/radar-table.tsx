import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { FreshnessLabel } from "@/components/ui/freshness";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { InfoTip } from "@/components/ui/tooltip";
import { formatUsd, shortenAddress } from "@/lib/format";

import {
  Figure,
  MeasuredValue,
  Unavailable,
  ageFromSeconds,
  formatMultiple,
  formatNumber,
  formatRatioPct,
  humanize,
} from "./display";
import type { MemeRow, PaperStatus } from "./types";

const PAPER_STATUS: Record<PaperStatus, string> = {
  none: "no paper position",
  open: "paper position open",
  closed: "paper position closed",
};

/** Capture instant reconstructed from an age so FreshnessLabel keeps its bands. */
function capturedAt(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

function Head({ children, tip }: { children: string; tip?: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {children}
      {tip ? <InfoTip label={children} content={tip} /> : null}
    </span>
  );
}

const COLUMNS: Column<MemeRow>[] = [
  {
    key: "meme",
    header: "Meme",
    pinned: true,
    cell: (row) => (
      <Link
        href={`/lifecycle-lab/${encodeURIComponent(row.slug)}`}
        className="font-medium text-accent hover:underline"
      >
        {row.display_name}
      </Link>
    ),
  },
  {
    key: "token",
    header: "Token",
    cell: (row) => {
      const primary = row.tokens.find((t) => t.mint === row.primary_mint) ?? row.tokens[0];
      if (!primary && !row.primary_mint) return <Unavailable reason="no linked token" />;
      return (
        <span className="flex flex-col leading-tight">
          <span className="text-ink">{primary?.symbol ?? "unnamed"}</span>
          <span data-numeric className="text-xs text-ink-3">
            {shortenAddress(row.primary_mint ?? primary?.mint)}
          </span>
        </span>
      );
    },
  },
  {
    key: "age",
    header: "Age",
    cell: (row) =>
      row.token_age_seconds === null && !row.age_bucket ? (
        <Unavailable reason="token age not known" />
      ) : (
        <span className="flex flex-col leading-tight">
          <span data-numeric>{ageFromSeconds(row.token_age_seconds)}</span>
          <span className="text-xs text-ink-3">{row.age_bucket ?? ""}</span>
        </span>
      ),
  },
  {
    key: "attention",
    header: <Head tip="Mentions across the attention sources in the last hour / 24 hours.">Attention 1h / 24h</Head>,
    align: "right",
    cell: (row) => (
      <span className="inline-flex items-baseline gap-1">
        <MeasuredValue measured={row.attention.mentions_1h} format={formatNumber} />
        <span className="text-ink-3">/</span>
        <MeasuredValue measured={row.attention.mentions_24h} format={formatNumber} />
      </span>
    ),
  },
  {
    key: "velocity",
    header: "Velocity",
    align: "right",
    cell: (row) => <MeasuredValue measured={row.attention.velocity} format={formatNumber} />,
  },
  {
    key: "acceleration",
    header: "Accel.",
    align: "right",
    cell: (row) => <MeasuredValue measured={row.attention.acceleration} format={formatNumber} />,
  },
  {
    key: "baseline",
    header: <Head tip="Current attention as a multiple of this meme's own baseline.">Vs baseline</Head>,
    align: "right",
    cell: (row) => (
      <MeasuredValue measured={row.attention.baseline_multiple} format={formatMultiple} />
    ),
  },
  {
    key: "platforms",
    header: "Platforms",
    align: "right",
    cell: (row) => <MeasuredValue measured={row.attention.platform_count} format={formatNumber} />,
  },
  {
    key: "state",
    header: (
      <Head tip="A description of where the meme sits in its attention/market cycle. States are descriptive, not a rating.">
        Lifecycle state
      </Head>
    ),
    // Neutral on purpose: a state is a description, not good or bad.
    cell: (row) =>
      row.lifecycle_state ? (
        <Badge tone="neutral">{humanize(row.lifecycle_state)}</Badge>
      ) : (
        <Unavailable reason="state not classified" />
      ),
  },
  {
    key: "activity",
    header: <Head tip="Growth in traded volume.">Market activity</Head>,
    align: "right",
    cell: (row) => <MeasuredValue measured={row.market_activity} format={formatRatioPct} />,
  },
  {
    key: "market",
    header: "Mcap / liq. / vol 1h",
    align: "right",
    cell: (row) => (
      <span className="inline-flex flex-col items-end leading-tight">
        <Figure value={row.market_cap} format={formatUsd} reason="market cap not reported" />
        <span className="text-xs text-ink-3">
          <Figure value={row.liquidity_usd} format={formatUsd} reason="liquidity not reported (bonding-curve pairs report none)" />
          {" / "}
          <Figure value={row.volume_1h} format={formatUsd} reason="volume not reported" />
        </span>
      </span>
    ),
  },
  {
    key: "freshness",
    header: "Data freshness",
    cell: (row) =>
      row.data_freshness_seconds === null ? (
        <Unavailable reason="no market reading yet" />
      ) : (
        <FreshnessLabel capturedAt={capturedAt(row.data_freshness_seconds)} />
      ),
  },
  {
    key: "paper",
    header: "Paper status",
    cell: (row) => (
      <span className="flex flex-col items-start gap-1">
        <span className="text-xs text-ink-2">{PAPER_STATUS[row.paper_status] ?? humanize(row.paper_status)}</span>
        {row.contains_backfill ? <Badge tone="warn">EXPLORATORY (backfill)</Badge> : null}
      </span>
    ),
  },
];

export function RadarTable({
  rows,
  isPending,
}: {
  rows: MemeRow[];
  isPending?: boolean;
}) {
  return (
    <Panel density="flush">
      <PanelHeader className="mb-0 p-4 pb-3">
        <PanelTitle>Meme radar</PanelTitle>
        <p className="max-w-[48ch] text-xs text-ink-3">
          What became interesting and why now. Unavailable means not collected —
          never zero.
        </p>
      </PanelHeader>
      <div className="px-2 pb-2">
        <DataTable
          caption="Tracked memes with attention, lifecycle state and market data"
          columns={COLUMNS}
          rows={rows}
          getRowId={(row) => row.slug}
          minWidth="1280px"
          isPending={isPending}
          empty={
            <p className="px-3 py-10 text-center text-sm text-ink-3">
              No memes are tracked yet. An empty radar is a truthful radar.
            </p>
          }
        />
      </div>
    </Panel>
  );
}
