"use client";

import { useCallback, useMemo, useState } from "react";

import { TokenCell } from "@/components/scanner/token-cell";
import { RadarScore } from "@/components/scanner/radar-score";
import { DataTable, useTableSort, type Column } from "@/components/ui/data-table";
import { FilterBar, SegmentedControl } from "@/components/ui/filters";
import { FreshnessLabel, LiveStatus, NoMarketData } from "@/components/ui/freshness";
import { Num } from "@/components/ui/num";
import { Toolbar } from "@/components/ui/toolbar";
import { InfoTip, Tooltip } from "@/components/ui/tooltip";
import { ErrorState } from "@/components/ui/states";
import { useFreshDetectedTokens } from "@/hooks/use-radar";
import { useSharedClock } from "@/hooks/use-shared-clock";
import { num } from "@/lib/design/bands";
import { compactAge, compactUsd } from "@/lib/radar-row";
import { cn } from "@/lib/utils";
import type { FreshDetectedToken, RadarCategory } from "@/types/radar";

/**
 * NEW LAUNCHES — what MEMESCOPE has detected most recently.
 *
 * WHICH ENDPOINT, AND WHY NOT THE OBVIOUS ONE
 *
 * `/tokens/latest` returns `TokenRead[]` — mint, name, symbol, image, creator,
 * slot, timestamps. **No price, no liquidity, no market cap, no score.** A
 * table built on it alone would have permanently empty market columns, and
 * filling them would take one request per row.
 *
 * `/radar/fresh-detections` is the same population — it calls the same
 * `TokenRepository.latest()` — joined to the newest market snapshot and the
 * Radar row, both batched. One request, no N+1, and its own docstring states
 * the rule this screen needs: *"leaving missing values blank, so a just-seen
 * token can appear as Detected without fabricating a score or market cap."*
 *
 * The backend already implements the honesty requirement. This screen renders
 * it. The only cost is a lower cap — 50 rows against `/tokens/latest`'s 100.
 *
 * THE PIPELINE IS THE POINT
 *
 * A token seconds old has no price because nothing has indexed a pool yet, and
 * no score because scoring runs after enrichment. Those are *stages*, not
 * failures, so the Stage column names where each token has reached instead of
 * showing a row of dashes and letting the reader assume the data is broken.
 */

type StageId = "detected" | "priced" | "scored" | "radar";

interface Stage {
  id: StageId;
  label: string;
  detail: string;
  className: string;
}

const STAGES: Record<StageId, Stage> = {
  detected: {
    id: "detected",
    label: "Detected",
    detail:
      "Seen on chain and recorded. No pool has been indexed yet, so there is no price to show — this is the normal first state for a new token.",
    className: "border-line text-ink-3",
  },
  priced: {
    id: "priced",
    label: "Priced",
    detail:
      "A market has been observed. Scoring runs after enrichment, so a score may not exist yet.",
    className: "border-line-strong text-ink-2",
  },
  scored: {
    id: "scored",
    label: "Scored",
    detail:
      "The Radar has evaluated this token but it is not currently an active opportunity.",
    className: "border-accent/30 text-accent",
  },
  radar: {
    id: "radar",
    label: "On radar",
    detail: "Currently an active Radar opportunity. It appears on the Scanner.",
    className: "border-up/35 bg-up/[0.08] text-up",
  },
};

/**
 * Which stage a detection has reached.
 *
 * Read from what the backend actually sent, in pipeline order. Nothing is
 * inferred beyond "a price exists" / "a radar row exists", both of which are
 * facts about MEMESCOPE's own processing rather than claims about the token.
 */
function stageOf(row: FreshDetectedToken): Stage {
  if (row.radar_status === "radar") return STAGES.radar;
  if (row.radar_status === "scored") return STAGES.scored;
  if (row.current_price !== null || row.market_observed_at !== null) return STAGES.priced;
  return STAGES.detected;
}

function StageChip({ row }: { row: FreshDetectedToken }) {
  const stage = stageOf(row);
  return (
    <Tooltip content={stage.detail} side="bottom">
      <span
        tabIndex={0}
        className={cn(
          "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-label font-medium uppercase",
          stage.className,
        )}
      >
        {stage.label}
      </span>
    </Tooltip>
  );
}

/** Age since detection, on the page's shared clock. */
function DetectedAge({ at }: { at: string }) {
  useSharedClock(1_000);
  const seconds = Math.max(0, (Date.now() - new Date(at).getTime()) / 1000);
  return (
    <Num
      value={seconds}
      display={compactAge(seconds)}
      tone={seconds < 300 ? "accent" : "muted"}
      className="text-xs"
    />
  );
}

const AT_SM = "hidden sm:table-cell";
const AT_LG = "hidden lg:table-cell";
const AT_XL = "hidden xl:table-cell";

type StageFilter = "all" | StageId;

const STAGE_FILTERS: { value: StageFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "detected", label: "Detected" },
  { value: "priced", label: "Priced" },
  { value: "radar", label: "On radar" },
];

export default function NewLaunchesPage() {
  const [stage, setStage] = useState<StageFilter>("all");
  const { data, isPending, isError, refetch } = useFreshDetectedTokens(50);

  const rows = useMemo(() => {
    const items = data ?? [];
    if (stage === "all") return items;
    return items.filter((row) => stageOf(row).id === stage);
  }, [data, stage]);

  const selectValue = useCallback((row: FreshDetectedToken, key: string) => {
    switch (key) {
      case "detected":
        return new Date(row.discovered_at).getTime();
      case "price":
        return num(row.current_price);
      case "marketCap":
        return num(row.current_market_cap);
      case "liquidity":
        return num(row.current_liquidity);
      case "score":
        return num(row.radar_score);
      default:
        return null;
    }
  }, []);

  const { sort, setSort, sorted } = useTableSort<FreshDetectedToken>(
    rows,
    selectValue,
    null,
  );

  const columns = useMemo<Column<FreshDetectedToken>[]>(
    () => [
      {
        key: "index",
        header: "#",
        align: "right",
        width: "40px",
        cell: (_row, index) => (
          <span data-numeric className="text-xs text-ink-3">
            {index + 1}
          </span>
        ),
      },
      {
        key: "token",
        header: "Token",
        pinned: true,
        width: "200px",
        cell: (row) => (
          <TokenCell
            mint={row.mint_address}
            name={row.name}
            symbol={row.symbol}
            imageUrl={row.image_url}
          />
        ),
      },
      {
        key: "detected",
        header: "Age",
        align: "right",
        width: "64px",
        sortable: true,
        srHeader: "Time since MEMESCOPE detected this token",
        cell: (row) => <DetectedAge at={row.discovered_at} />,
      },
      {
        key: "stage",
        header: "Stage",
        width: "92px",
        srHeader: "How far this token has moved through the pipeline",
        cell: (row) => <StageChip row={row} />,
      },
      {
        key: "price",
        header: "Price",
        align: "right",
        width: "84px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.current_price}
            display={compactUsd(row.current_price)}
            className="text-sm"
          />
        ),
      },
      {
        key: "marketCap",
        header: "Mkt cap",
        align: "right",
        width: "84px",
        sortable: true,
        headerClassName: AT_SM,
        cellClassName: AT_SM,
        cell: (row) => (
          <Num
            value={row.current_market_cap}
            display={compactUsd(row.current_market_cap)}
            className="text-sm"
          />
        ),
      },
      {
        key: "liquidity",
        header: "Liquidity",
        align: "right",
        width: "84px",
        sortable: true,
        headerClassName: AT_LG,
        cellClassName: AT_LG,
        cell: (row) => (
          <Num
            value={row.current_liquidity}
            display={compactUsd(row.current_liquidity)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "score",
        header: "Score",
        align: "right",
        width: "112px",
        sortable: true,
        srHeader: "MEMESCOPE score, where one exists",
        // `xl`, not `lg`: measured at exactly 1024px the liquidity and score
        // columns together pushed the table 64px past the available width.
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => (
          <RadarScore
            score={row.radar_score}
            category={(row.radar_category as RadarCategory | null) ?? null}
          />
        ),
      },
      {
        key: "metadata",
        header: "Metadata",
        width: "88px",
        srHeader: "Whether token metadata has resolved",
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => (
          <span
            className={cn(
              "text-xs",
              row.metadata_status === "resolved"
                ? "text-ink-2"
                : row.metadata_status === "failed"
                  ? "text-down"
                  : "text-ink-3",
            )}
          >
            {row.metadata_status === "resolved"
              ? "Resolved"
              : row.metadata_status === "failed"
                ? "Failed"
                : "Pending"}
          </span>
        ),
      },
      {
        key: "data",
        header: "Data",
        width: "80px",
        srHeader: "How old the market reading is",
        headerClassName: AT_SM,
        cellClassName: AT_SM,
        cell: (row) =>
          row.market_observed_at ? (
            <FreshnessLabel capturedAt={row.market_observed_at} className="text-xs" />
          ) : (
            // Not stale — never observed. A different claim.
            <NoMarketData className="text-xs" />
          ),
      },
    ],
    [],
  );

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        eyebrow="New launches"
        title="Most recently detected"
        actions={
          <LiveStatus
            timestamps={(data ?? []).map((row) => row.market_observed_at)}
            pending={isPending}
          />
        }
        filters={
          <div className="flex flex-col gap-2.5">
            <FilterBar>
              <SegmentedControl
                label="Stage"
                options={STAGE_FILTERS}
                value={stage}
                onChange={(value) => setStage(value as StageFilter)}
              />
            </FilterBar>
            <p className="flex items-center gap-1.5 text-xs text-ink-3">
              <span data-numeric>
                {sorted.length} of {data?.length ?? 0}
              </span>
              <span>newest detections</span>
              <InfoTip
                label="these stages"
                content="Detection, market enrichment and scoring are separate stages that complete at different times. A token with no price has not failed — nothing has indexed a pool for it yet."
              />
            </p>
          </div>
        }
      />

      {isError ? (
        <ErrorState
          body="The discovery feed is not responding. Detections already recorded are safe — this view will recover on its own."
          onRetry={() => void refetch()}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={sorted}
          getRowId={(row) => row.mint_address}
          caption="Most recently detected tokens, newest first"
          sort={sort}
          onSortChange={setSort}
          density="compact"
          stickyHeader
          maxHeight="calc(100dvh - 18rem)"
          minWidth="640px"
          isPending={isPending}
          pendingRows={12}
          empty={
            <div className="px-3 py-12 text-center">
              <p className="text-sm text-ink">
                {stage === "all"
                  ? "No detections yet"
                  : "Nothing at that stage right now"}
              </p>
              <p className="mt-1.5 text-xs text-ink-3">
                {stage === "all"
                  ? "Discovery has not recorded a new token yet. This feed fills as launches are seen on chain."
                  : "Tokens move through detection, pricing and scoring at different speeds."}
              </p>
            </div>
          }
        />
      )}
    </div>
  );
}
