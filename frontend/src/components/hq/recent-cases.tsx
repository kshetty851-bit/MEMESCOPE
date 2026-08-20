"use client";

import { Panel } from "@/components/ui/panel";
import { usePaperPositions } from "@/hooks/use-paper";
import { useRadar } from "@/hooks/use-radar";

/**
 * RECENT CASES.
 *
 * A compact list, not a room and not a full journey — the brief is explicit
 * that this is a small board surface, not HQ-8's Mission Board. Every row
 * comes from data the page has already loaded in bulk (`usePaperPositions`,
 * `useRadar`), so this list costs nothing beyond what the visible packets
 * already fetch.
 *
 * WHY EVERY ROW IS NOT A FULL SIX-STAGE SUMMARY
 *
 * The brief's own example shows a per-row verdict like "ATLAS FAILED" —  but
 * an Atlas reading only exists per mint, from a query §29 restricts to a
 * visible packet or an opened case file, on pain of exactly the N+1 storm
 * that section forbids. Fetching it for every row here would violate that
 * limit the moment the list grew past three. So each row shows the coarsest
 * fact the *already-loaded* batch responses can support without a further
 * request — bought (from the positions list, which is already whole) or
 * discovered (from the Radar list) — and clicking through to the full case
 * file is what unlocks Luna, Dex, Atlas and Decision, each fetched exactly
 * once, for exactly the mint the reader asked about.
 */

const RECENT_LIMIT = 6;

export interface RecentCasesProps {
  onSelectCase: (mint: string) => void;
}

export function RecentCases({ onSelectCase }: RecentCasesProps) {
  const radar = useRadar({ sort: "detected", pageSize: RECENT_LIMIT });
  const positions = usePaperPositions();

  const boughtMints = new Set((positions.data?.items ?? []).map((p) => p.mint_address));
  const rows = (radar.data?.items ?? []).slice(0, RECENT_LIMIT);

  if (rows.length === 0) return null;

  return (
    <Panel>
      <div className="flex flex-col gap-2 p-4" data-testid="hq-recent-cases">
        <h2 className="text-sm font-semibold text-[var(--color-ink)]">Recent Cases</h2>
        <ul className="flex flex-col gap-1">
          {rows.map((entry) => {
            const bought = boughtMints.has(entry.mint_address);
            return (
              <li key={entry.mint_address}>
                <button
                  type="button"
                  onClick={() => onSelectCase(entry.mint_address)}
                  className="flex w-full items-center justify-between gap-3 rounded-md border border-[var(--color-line)] px-3 py-1.5 text-left text-xs"
                >
                  <span className="truncate text-[var(--color-ink)]">
                    {entry.symbol ?? entry.name ?? entry.mint_address.slice(0, 6)}
                  </span>
                  <span
                    className="hq-case-chip shrink-0"
                    data-status={bought ? "PASSED" : "PENDING"}
                  >
                    {bought ? "Rex · Bought" : "Radar · Discovered"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </Panel>
  );
}
