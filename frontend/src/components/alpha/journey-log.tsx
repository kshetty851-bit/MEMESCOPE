"use client";

import { useState } from "react";

/**
 * THE DAY-BY-DAY LOG, inside the journey section (Karthik, 2026-09-27:
 * "mention this also in homepage and keep updating").
 *
 * Each day's commit count is live, from GitHub through `/journey`. A day up
 * to 27 Sep 2026 reads in the plain words below, written from that day's
 * commits; any later day writes itself from its own commit titles, so the
 * log keeps growing without anyone editing this file. A line added here for
 * a new day replaces its automatic words.
 */

export interface LogDay {
  date: string;
  commits: number;
  titles: string[];
}

export const WRITTEN: Record<string, string> = {
  "2026-07-27": "Day 1. Project set up, Solana token discovery, the token details engine, the design bible and roadmap, and the first space-themed frontend.",
  "2026-07-29": "The AI scoring engine, Opportunity Radar, track record, Exit Watch, Hall of Fame and Lessons, deploy scripts and backups, and a daily mission briefing.",
  "2026-07-30": "Six specialist analysts, watchlists and an event log.",
  "2026-08-02": "Platform fixes and the Opportunity Engine.",
  "2026-08-03": "Outcomes and analytics for the Opportunity Engine.",
  "2026-08-04": "Sprints 19–28 in one day: the Track Record, the Radar as the homepage, the first paper wallet, the Strategy Lab, and trading costs beside gross returns.",
  "2026-08-05": "Paper Wallet V2, with a reset to keep it honest.",
  "2026-08-08": "The alpha access landing page, production deploy setup, and Jupiter’s trading costs for the paper wallet.",
  "2026-08-09": "Token logos and names, the real-wallet safety gate, and the first steps toward a real wallet.",
  "2026-08-11": "A frontend rebuild and a launch sequence.",
  "2026-08-19": "Real wallet test-network phase 2, and paper wallet fixes.",
  "2026-08-20": "MEMESCOPE HQ is born: the cartoon office, its meetings and its cats. A security gate for the paper wallet.",
  "2026-08-21": "New-token tracking, data retention, and a second data-update service.",
  "2026-08-22": "HQ’s reliability desk, and Karthik’s own paper wallet.",
  "2026-08-23": "A false alarm in Karthik’s wallet checks, fixed.",
  "2026-08-24": "The Opportunity Engine retired (10,428 lines deleted), Chainstack for chain data, and the V5 Forward Arena: five $1,000 portfolios.",
  "2026-08-25": "Twenty frozen strategies on twenty $1,000 wallets, the real wallet’s start/stop switch, and its isolated signer.",
  "2026-08-26": "The real wallet goes live: signer, real orders, the driver, selling, and withdrawals that can only reach Karthik.",
  "2026-08-27": "HQ watches the wallet, larger size limits, and a filtered twin of V6-07.",
  "2026-09-04": "The take-profit contest, the Compound Lab, a copy-trading lab and Momentum V2.",
  "2026-09-07": "The Depth Lab, twenty wallets that differ in one number. The Forward Arena retired.",
  "2026-09-08": "The Social Lab, a copy-trade control, the first graduation tracking, and the 5-minute Hold Lab.",
  "2026-09-09": "Graduation Lab v1 (deleted the same day: every arm lost), Movers, KOL and Matrix labs, and fixes for coins wrongly marked dead.",
  "2026-09-10": "The Rafiq Lab, Rafiq’s five strategies. KOL, Matrix and Movers deleted.",
  "2026-09-11": "The NSE Breakout Tracker, and the Graduation Lab rebuilt properly from free data: backtester and paper book.",
  "2026-09-12": "The busiest day: a 50-arm graduation contest, Rafiq F2, and the SOL price in the menu bar.",
  "2026-09-13": "A fast-buying lab (no edge), the Forex Lab (failed), and a measured grid of strategy variants.",
  "2026-09-14": "Buying before graduation tested (worse), a hold-time sweep, and performance projections.",
  "2026-09-15": "Deep pools only, and B3 offered to the real wallet.",
  "2026-09-16": "Live price checks every second; the real wallet buys and sells on its own.",
  "2026-09-17": "Rafiq G1, WhatsApp trade alerts, the office dances to music, and the server load fixed.",
  "2026-09-18": "Rug-money blocks and a check against coins where one holder owns over 10%.",
  "2026-09-19": "The Tape Lab, the first test that passed; the Momentum and Rafiqv2 labs; every clock in Dubai time.",
  "2026-09-20": "The quiet-pool rule is born.",
  "2026-09-21": "G-QUIET offered to the real wallet.",
  "2026-09-22": "A 4-minute option, the $55–75k band, the B3 decision book, and Momentum run 2.",
  "2026-09-23": "Karthik’s Lab starts: the quiet rule, judged on 23 October.",
  "2026-09-24": "Daily rows in the lab, a new homepage and the space crew.",
  "2026-09-25": "G-Q150, a big clean-up of labs that had failed, a talking crew, one trade at a time, and cartoon planets.",
  "2026-09-26": "The moon-landing intro, every pool size tested, and credits for Rafiq and Ashwin.",
  "2026-09-27": "Panda news TV, the $75k+ book, a size-by-pool grid, the 2-minute entry guard, USER 1–10 wallets, and this section.",
};

/** "feat(lab): a thing (#12)" -> "A thing". */
export function plain(title: string): string {
  const text = title
    .replace(/\s*\(#\d+\)\s*$/, "")
    .replace(/^[a-z-]+(\([^)]*\))?!?:\s*/i, "")
    .trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Written days and live days together, newest first. */
export function mergeDays(live: LogDay[]): { date: string; commits: number | null; words: string }[] {
  const byDate = new Map(live.map((d) => [d.date, d]));
  const dates = new Set([...Object.keys(WRITTEN), ...byDate.keys()]);
  return [...dates]
    .sort()
    .reverse()
    .map((date) => {
      const day = byDate.get(date);
      const words = WRITTEN[date] ?? (day?.titles.slice(0, 3).map(plain).join(" · ") || "Maintenance and fixes.");
      return { date, commits: day?.commits ?? null, words };
    });
}

function label(date: string): string {
  const d = new Date(`${date}T12:00:00Z`);
  return d
    .toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" })
    .replace("Sept", "Sep")
    .toUpperCase();
}

export function DayLog({ days }: { days: LogDay[] | undefined }) {
  const [all, setAll] = useState(false);
  const rows = mergeDays(days ?? []);
  const shown = all ? rows : rows.slice(0, 7);
  return (
    <div className="journey-card journey-log">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-accent">Research log · day by day</p>
        <p className="text-xs text-ink-3">
          {rows.length} working days{days ? " · live from GitHub" : ""}
        </p>
      </div>
      <ol className="mt-4">
        {shown.map((row) => (
          <li key={row.date} className="journey-log-row">
            <span className="font-mono text-xs text-accent">{label(row.date)}</span>
            <p className="text-sm leading-relaxed text-ink-2">{row.words}</p>
            <span className="text-right font-mono text-xs tabular-nums text-ink-3">
              {row.commits === null ? "" : `${row.commits} commit${row.commits === 1 ? "" : "s"}`}
            </span>
          </li>
        ))}
      </ol>
      {rows.length > 7 ? (
        <button
          type="button"
          onClick={() => setAll(!all)}
          aria-expanded={all}
          className="mt-3 text-sm text-accent hover:text-accent-strong"
        >
          {all ? "Show the latest week" : `Show all ${rows.length} days`}
        </button>
      ) : null}
    </div>
  );
}
