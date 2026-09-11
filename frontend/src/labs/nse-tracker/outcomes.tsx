"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";

import { count, plainPct, pct, TONE_CLASS, tone } from "./format";
import type { Stats } from "./types";

/**
 * THE PANEL THAT MATTERS.
 *
 * Two questions, side by side: does a higher score break out more often, and
 * does it return more when it does? The replay answers both from three years
 * of history; the live column answers neither until its first windows close,
 * and says so rather than showing zeros.
 *
 * Nothing here is computed. Every figure arrives from `/stats`, which also
 * ships the thresholds that produced it — so a number on this page can never
 * be read against the wrong rules.
 */

export function OutcomesCard({
  replay,
  live,
}: {
  replay: Stats | undefined;
  live: Stats | undefined;
}) {
  if (!replay && !live) {
    return (
      <Panel density="flush">
        <PanelHeader className="px-4 pt-3">
          <PanelTitle>Outcomes</PanelTitle>
        </PanelHeader>
        <EmptyState
          title="No episodes recorded yet"
          body="Run the historical replay to fill this from three years of bars, or wait for the live pass to open its first setups."
        />
      </Panel>
    );
  }

  return (
    <Panel density="flush" data-testid="outcomes-card">
      <PanelHeader className="px-4 pt-3">
        <PanelTitle>Outcomes</PanelTitle>
      </PanelHeader>

      <div className="grid gap-4 border-b border-line p-4 md:grid-cols-2">
        <SourceColumn title="Replay — 3 years" stats={replay} />
        <SourceColumn title="Live" stats={live} />
      </div>

      {replay && replay.by_score_decile.length > 0 && (
        <div className="p-4">
          <p className="mb-1 text-label uppercase text-ink-4">
            Does the score predict anything?
          </p>
          <p className="mb-3 max-w-2xl text-xs text-ink-3">
            Two different questions. The left column is whether the setup
            cleared its level; the right is what happened to the money
            afterwards. A score can rank one and not the other.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="decile-table">
              <thead className="text-label uppercase text-ink-4">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 text-left">Score</th>
                  <th className="px-3 py-2 text-right">Episodes</th>
                  <th className="px-3 py-2 text-right">Reached breakout</th>
                  <th className="px-3 py-2 text-right">+20d from break</th>
                  <th className="px-3 py-2 text-right">+20d from ref</th>
                  <th className="py-2 pl-3 text-right">Win rate</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {replay.by_score_decile.map((row) => (
                  <tr key={row.decile} data-testid="decile-row"
                    className="border-b border-line/50">
                    <td className="py-2 pr-3 text-left text-ink">
                      {row.score_range}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {count(row.n)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink">
                      {plainPct(row.reached_breakout_pct)}
                    </td>
                    <td className={`px-3 py-2 text-right ${
                      TONE_CLASS[tone(row.mean_ret_bo_20)]}`}>
                      {pct(row.mean_ret_bo_20, 2)}
                    </td>
                    <td className={`px-3 py-2 text-right ${
                      TONE_CLASS[tone(row.mean_ret_ref_20)]}`}>
                      {pct(row.mean_ret_ref_20, 2)}
                    </td>
                    <td className="py-2 pl-3 text-right text-ink-3">
                      {plainPct(row.win_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {replay.by_year.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-label uppercase text-ink-4">By year</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs" data-testid="year-table">
                  <thead className="text-label uppercase text-ink-4">
                    <tr className="border-b border-line">
                      <th className="py-2 pr-3 text-left">Year</th>
                      <th className="px-3 py-2 text-right">Episodes</th>
                      <th className="px-3 py-2 text-right">Reached breakout</th>
                      <th className="px-3 py-2 text-right">+20d from break</th>
                      <th className="py-2 pl-3 text-right">vs Nifty</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono tabular-nums">
                    {replay.by_year.map((row) => (
                      <tr key={row.year} className="border-b border-line/50">
                        <td className="py-2 pr-3 text-left text-ink-2">
                          {row.year}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-3">
                          {count(row.episodes)}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-3">
                          {plainPct(row.reached_breakout_pct)}
                        </td>
                        <td className={`px-3 py-2 text-right ${
                          TONE_CLASS[tone(row.mean_ret_bo_20)]}`}>
                          {pct(row.mean_ret_bo_20, 2)}
                        </td>
                        <td className={`py-2 pl-3 text-right ${
                          TONE_CLASS[tone(row.rel_nifty_20_mean)]}`}>
                          {pct(row.rel_nifty_20_mean, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {replay.caveats?.length ? (
            <ul className="mt-4 space-y-1 border-t border-line pt-3"
              data-testid="caveats">
              {replay.caveats.map((caveat) => (
                <li key={caveat} className="text-xs text-ink-4">
                  — {caveat}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

function SourceColumn({ title, stats }: { title: string; stats: Stats | undefined }) {
  if (!stats || stats.episodes === 0) {
    return (
      <div data-testid="source-column">
        <p className="text-label uppercase text-ink-4">{title}</p>
        <p className="mt-2 text-sm text-ink-3">No episodes yet.</p>
      </div>
    );
  }
  const measured = stats.from_ref.n > 0;
  return (
    <div data-testid="source-column">
      <p className="text-label uppercase text-ink-4">{title}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2">
        <Figure label="Episodes" value={count(stats.episodes)} />
        <Figure label="Reached breakout"
          value={plainPct(stats.reached_breakout_pct)} />
        <Figure label="False breakouts"
          value={plainPct(stats.false_breakout_pct)} />
        <Figure label="Median days to break"
          value={stats.days_to_breakout_median === null
            || stats.days_to_breakout_median === undefined
            ? "—" : `${stats.days_to_breakout_median}`} />
      </dl>
      {measured ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3">
          <Figure label="+20d from ref" value={pct(stats.from_ref.mean_ret_20, 2)}
            toneKey={tone(stats.from_ref.mean_ret_20)} />
          <Figure label="+20d from break"
            value={pct(stats.from_breakout.mean_ret_20, 2)}
            toneKey={tone(stats.from_breakout.mean_ret_20)} />
          <Figure label="Win rate (ref)"
            value={plainPct(stats.from_ref.win_rate_20)} />
          <Figure label="vs Nifty" value={pct(stats.rel_nifty_20_mean, 2)}
            toneKey={tone(stats.rel_nifty_20_mean)} />
          <Figure label="Trail 10% PF"
            value={stats.trail10.profit_factor === null
              || stats.trail10.profit_factor === undefined
              ? "—" : stats.trail10.profit_factor.toFixed(2)} />
          <Figure label="Trail stopped out"
            value={plainPct(stats.trail10.stopped_pct)} />
        </dl>
      ) : (
        /* Not zeros. An episode whose 40-bar window is still open has no
           return, and drawing that as 0.0% would read as a flat trade. */
        <p className="mt-3 border-t border-line pt-3 text-xs text-ink-4"
          data-testid="not-measured-yet">
          No outcome windows have closed yet — returns need 40 trading days
          after the setup, so the first of these appears about two months in.
        </p>
      )}
    </div>
  );
}

function Figure({ label, value, toneKey }: {
  label: string; value: string; toneKey?: "up" | "down" | "flat";
}) {
  return (
    <div>
      <dt className="text-label uppercase text-ink-4">{label}</dt>
      <dd className={`font-mono text-xs tabular-nums ${
        toneKey ? TONE_CLASS[toneKey] : "text-ink-2"}`}>
        {value}
      </dd>
    </div>
  );
}
