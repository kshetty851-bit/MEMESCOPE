"use client";

import { Fragment, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { formatPrice, shortenAddress } from "@/lib/format";

import {
  Figure,
  Unavailable,
  formatPlainUsd,
  formatRatioPct,
  formatSignedUsd,
  formatUtc,
  humanize,
} from "./display";
import type { PaperTrade } from "./types";

function Timeline({ trade }: { trade: PaperTrade }) {
  if (trade.evidence_timeline.length === 0) {
    return (
      <p className="text-xs text-ink-3">
        <Unavailable reason="no evidence timeline recorded for this trade" />
      </p>
    );
  }
  return (
    <ol className="flex flex-col gap-1.5 border-l border-line pl-4">
      {trade.evidence_timeline.map((step, i) => (
        <li key={`${step.at}-${i}`} className="text-xs">
          <span data-numeric className="text-ink-3">
            {formatUtc(step.at)}
          </span>{" "}
          <span className="font-medium text-ink-2">{humanize(step.kind)}</span>
          {step.detail ? <span className="text-ink-2"> — {step.detail}</span> : null}
        </li>
      ))}
    </ol>
  );
}

/**
 * PAPER TRADES — simulated paper entries and paper exits on the research
 * ledger. Each row expands to the evidence that was visible when the paper
 * entry was taken, in time order.
 */
export function TradesPanel({ trades }: { trades: PaperTrade[] }) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Panel density="flush">
      <PanelHeader className="mb-0 p-4 pb-3">
        <PanelTitle>Paper trades</PanelTitle>
        <Badge tone="warn">PAPER ONLY — no real trading</Badge>
      </PanelHeader>
      {trades.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-ink-3">
          No paper entries for this meme.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <caption className="sr-only">Paper trades with expandable evidence timelines</caption>
            <thead>
              <tr className="border-y border-line bg-sunken text-left text-label uppercase text-ink-3">
                <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
                <th scope="col" className="px-3 py-2 font-medium">Token</th>
                <th scope="col" className="px-3 py-2 font-medium">Paper entry</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Entry price</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Size</th>
                <th scope="col" className="px-3 py-2 font-medium">Paper exit</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">P&amp;L</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Return</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const expanded = open === t.trade_key;
                const panelId = `evidence-${t.trade_key}`;
                return (
                  <Fragment key={t.trade_key}>
                    <tr className="border-b border-line-subtle align-top" data-testid="paper-trade">
                      <td className="px-4 py-2">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-controls={expanded ? panelId : undefined}
                          onClick={() => setOpen(expanded ? null : t.trade_key)}
                          className="rounded-sm border border-line px-2 py-0.5 text-xs text-ink-2 hover:border-line-strong hover:text-ink"
                        >
                          {expanded ? "Hide" : "Show"} evidence ({t.evidence_timeline.length})
                        </button>
                      </td>
                      <td className="px-3 py-2" data-numeric>{shortenAddress(t.mint)}</td>
                      <td className="px-3 py-2" data-numeric>
                        <span className="flex flex-col leading-tight">
                          <span>{formatUtc(t.entry_at)}</span>
                          <span className="text-xs text-ink-3">
                            {t.entry_reason ? humanize(t.entry_reason) : ""}
                          </span>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Figure value={t.entry_price} format={formatPrice} reason="entry price not recorded" />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Figure value={t.size_usd} format={formatPlainUsd} />
                      </td>
                      <td className="px-3 py-2" data-numeric>
                        {t.exit_at ? (
                          <span className="flex flex-col leading-tight">
                            <span>{formatUtc(t.exit_at)}</span>
                            <span className="text-xs text-ink-3">
                              {t.exit_reason ? humanize(t.exit_reason) : ""}
                              {t.exit_price ? ` @ ${formatPrice(t.exit_price)}` : ""}
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-ink-3">not exited</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Figure
                          value={t.pnl_usd}
                          format={formatSignedUsd}
                          reason={t.exit_at ? "pnl not recorded" : "paper position still open"}
                        />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Figure
                          value={t.return_pct}
                          format={formatRatioPct}
                          reason={t.exit_at ? "return not recorded" : "paper position still open"}
                        />
                      </td>
                      <td className="px-3 py-2">
                        <Badge tone="neutral">{humanize(t.status)}</Badge>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="border-b border-line-subtle bg-sunken" id={panelId}>
                        <td colSpan={9} className="px-4 py-3">
                          <p className="mb-2 text-label font-medium uppercase text-ink-3">
                            Evidence timeline
                          </p>
                          <Timeline trade={t} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
