"use client";

import { useEffect, useState } from "react";

import {
  AGED_BLURB,
  FRESH_BLURB,
  MatrixSection,
  money,
} from "@/components/lab/matrix-grid";
import { LabTradesTable } from "@/components/lab/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";

import { useMatrixBoard, useMatrixTrades } from "@/hooks/use-matrix";

/**
 * THE MATRIX LAB — twenty-four wallets laid out as a grid, not a leaderboard.
 *
 * The layout is the argument. Each section is a table whose ROWS are book
 * shapes and whose COLUMNS are holding periods, so two adjacent cells differ
 * in exactly one thing and a whole row or column reads as a dose-response.
 *
 * Nothing on this page sorts, highlights or ranks by outcome. With
 * twenty-four books the single best line is very probably noise — V6 ran
 * twenty wallets here and eighteen finished below the failure floor — and a
 * board that put the leader on top would invite precisely the reading this
 * design exists to prevent. The only interaction is picking a cell to read
 * its trades.
 */

export default function MatrixLabPage() {
  const { data, isLoading, isError } = useMatrixBoard();
  const [selected, setSelected] = useState<string | null>(null);
  const trades = useMatrixTrades(selected ?? undefined);

  // A cell picked on the Movers Lab page arrives as `/matrix-lab#F-05-2`.
  // Read once on mount — a hash, not a search param, so the page stays
  // statically renderable without a Suspense boundary.
  useEffect(() => {
    const arm = window.location.hash.replace(/^#/, "");
    if (/^[FA]-(05|15|30|NC)-(2|10|20)$/.test(arm)) setSelected(arm);
  }, []);
  const starting = Number(data?.starting_equity ?? 100);

  const fresh = (data?.wallets ?? []).filter((w) => w.section === "FRESH");
  const aged = (data?.wallets ?? []).filter((w) => w.section === "AGED");

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Matrix Lab"
        title="Two populations, four clocks, three book shapes"
        description="Twenty-four $100 paper wallets arranged as a factorial: fresh pump.fun launches in one section, tokens at least 24 hours old in the other, each crossed with a 5, 15 or 30 minute hold or no clock at all, and with a $2 x 50, $10 x 10 or $20 x 5 book. Every arm banks at +10% and compounds from what it realised. Nothing here is real money."
      />

      {/* Above the numbers and not collapsible: with this many books the
          headline number is the easiest thing on the page to misread. */}
      <Panel density="compact">
        <Label>WHAT THIS CAN AND CANNOT SHOW</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "A grid, not a horse race. Twenty-four wallets differing one dimension at a time. No real order was ever placed."}
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
            opened, so none of the arms are trading yet.
          </p>
        </Panel>
      ) : (
        <>
          <Panel density="compact">
            <Label>THE RULES BOTH SECTIONS SHARE</Label>
            <p className="mt-2 text-xs text-muted">
              Liquidity at least{" "}
              <span className="font-mono text-ink">
                {money(Number(data.min_liquidity_usd))}
              </span>{" "}
              · bank the wallet at{" "}
              <span className="font-mono text-ink">
                {data.target_multiple ?? "1.10"}x
              </span>{" "}
              and compound from what was realised · no take-profit and no stop on
              any position · every book fully deployable
            </p>
          </Panel>

          <MatrixSection
            title="FRESH — pump.fun launches"
            blurb={FRESH_BLURB}
            wallets={fresh}
            starting={starting}
            selected={selected}
            onSelect={setSelected}
          />

          <MatrixSection
            title={`AGED — established markets, at least ${data.min_age_hours ?? "24"}h old`}
            blurb={AGED_BLURB}
            wallets={aged}
            starting={starting}
            selected={selected}
            onSelect={setSelected}
          />

          <Panel density="compact">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Label>{selected ? `TRADES · ${selected}` : "TRADES · ALL ARMS"}</Label>
              {selected ? (
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="font-mono text-[10px] uppercase text-muted hover:text-ink"
                >
                  show all
                </button>
              ) : (
                <span className="font-mono text-[10px] text-muted">
                  pick a cell above to isolate one arm
                </span>
              )}
            </div>
          </Panel>

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
