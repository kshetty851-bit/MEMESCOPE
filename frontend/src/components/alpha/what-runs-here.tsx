"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api-client";

/**
 * WHAT ACTUALLY RUNS HERE, and who built it.
 *
 * This replaced a 4,700px section about the Radar, the track record and the
 * paper wallet (2026-09-24), none of which the owner uses. What the site is
 * now is a strategy lab: graduations bought on paper by competing rules, one
 * book of the owner's own, a real wallet that follows a rule only once it has
 * earned it, and the HQ office that watches all of it.
 *
 * The one live figure is Karthik's Lab, the only thing the owner chose to show
 * publicly. It comes from `/labs/graduation/karthik/summary`, the one lab read
 * the site-code gate lets through, and it carries headline numbers only.
 * Nothing on this page reads the real wallet.
 */

interface LabSummary {
  started_at: string;
  judge_at: string;
  capital_usd: string;
  balance_usd: string;
  pnl_usd: string;
  pnl_pct: string;
  trades: number;
  rugs: number;
}

const DAY_MS = 86_400_000;

function usd(value: string): string {
  const n = Number(value);
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** "Day 2 of 30": whole days since the start, counting the first as day one. */
export function dayOf(startIso: string, judgeIso: string, now = Date.now()): string {
  const start = new Date(startIso).getTime();
  const total = Math.round((new Date(judgeIso).getTime() - start) / DAY_MS);
  const day = Math.min(total, Math.max(1, Math.floor((now - start) / DAY_MS) + 1));
  return `Day ${day} of ${total}`;
}

function LiveLab() {
  const [lab, setLab] = useState<LabSummary | null>(null);
  useEffect(() => {
    let live = true;
    api
      .get<LabSummary>("/labs/graduation/karthik/summary", { skipAuthRetry: true })
      .then((data) => live && setLab(data))
      .catch(() => {
        // The card reads fine without the figure; a failed read is not news.
      });
    return () => {
      live = false;
    };
  }, []);
  if (!lab) return <p className="mt-3 text-sm text-ink-3">A $600 paper book, judged after 30 days.</p>;
  const up = Number(lab.pnl_usd) >= 0;
  return (
    <div className="mt-3">
      <p className="text-label text-ink-3">{dayOf(lab.started_at, lab.judge_at)} · live</p>
      <p className="mt-1 text-2xl font-medium tabular-nums text-ink">
        {usd(lab.balance_usd)}{" "}
        <span className={up ? "text-up" : "text-down"}>
          {up ? "+" : ""}
          {Number(lab.pnl_pct).toFixed(2)}%
        </span>
      </p>
      <p className="mt-1 text-xs text-ink-3">
        {lab.trades} trades · {lab.rugs} rugs · started with {usd(lab.capital_usd)} of paper money
      </p>
    </div>
  );
}

const PLACES = [
  {
    href: "/graduation-lab",
    name: "Graduation Lab",
    what: "Every pump.fun graduation over the depth line is bought on paper by a set of rules at once, each beside a control it has to beat.",
  },
  {
    href: "/karthik-lab",
    name: "Karthik's Lab",
    what: null, // the live figure stands in for the description
  },
  {
    href: "/real-wallet",
    name: "Real wallet",
    what: "Real SOL follows a rule only once it has earned it, sells after five minutes, and can only ever withdraw to its owner.",
  },
  {
    href: "/hq",
    name: "HQ",
    what: "The office where each desk watches one part of the machine, live, and says what it sees.",
  },
] as const;

export function WhatRunsHere() {
  return (
    <section
      aria-labelledby="runs-heading"
      className="relative z-10 mx-auto w-full max-w-[80rem] px-6 py-20 lg:px-10"
    >
      <p className="text-label text-accent">What runs here</p>
      <h2 id="runs-heading" className="mt-3 max-w-2xl text-2xl font-medium tracking-tight text-ink">
        A lab for pump.fun graduations, not a list of tips.
      </h2>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-2">
        Most strategies tested here have not worked, and the lab keeps those results
        beside the ones that did. Real money only follows what has earned it.
      </p>
      <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PLACES.map((place) => (
          <li key={place.href}>
            <Link
              href={place.href}
              className="block h-full rounded-lg border border-line bg-canvas/70 p-5 transition-colors hover:border-accent/60"
            >
              <p className="text-base font-medium text-ink">{place.name} →</p>
              {place.what ? (
                <p className="mt-3 text-sm leading-relaxed text-ink-2">{place.what}</p>
              ) : (
                <LiveLab />
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="relative z-10 mx-auto w-full max-w-[80rem] border-t border-line-subtle px-6 py-8 lg:px-10">
      <p className="text-sm text-ink-2">
        Designed and built by <span className="font-medium text-ink">Karthik Shetty</span>
      </p>
      <p className="mt-1 text-xs text-ink-3">Dubai · 2026</p>
    </footer>
  );
}
