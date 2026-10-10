"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Character, RigDefs, portraitViewBox } from "@/components/hq/character-rig";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import type { CharacterDefinition, CharacterLook } from "@/lib/hq/characters";
import { api } from "@/lib/api-client";

/**
 * NSE LAB (Karthik, 2026-10-10: "build NSE Lab with one agent who looks like a
 * human — his job is to go to screener.in and provide me details"). Arjun
 * reads one company's screener.in page when asked and lays out a fixed card.
 * Admin only and never stored: screener.in allows personal viewing only.
 */

export const ARJUN: CharacterLook = {
  id: "nse-arjun", bodyType: "tall", headShape: "oval", skinTone: "s3", hair: "undercut",
  hairTone: "h2", outfit: "rolled-shirt", accessory: "glasses", palette: "indigo", defaultPose: "standing",
};

type Series = { periods: string[]; values: string[] } | null;
export interface CompanyCard {
  name: string | null;
  symbol: string;
  url: string;
  consolidated: boolean;
  about: string | null;
  ratios: { name: string; value: string }[];
  growth: { title: string; rows: [string, string][] }[];
  quarters: { Sales: Series; "Net Profit": Series };
  yearly: { Sales: Series; "Net Profit": Series };
  borrowings: Series;
  promoters: Series;
  pros: string[];
  cons: string[];
  fetched_at: string;
}

function SeriesTable({ title, rows }: { title: string; rows: [string, Series][] }) {
  const head = rows.find(([, s]) => s)?.[1];
  if (!head) return null;
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-2">{title}</div>
      <table className="w-full text-[13px] tabular-nums">
        <thead className="text-[11px] text-ink-dim">
          <tr>
            <th className="py-1 pr-2 text-left font-normal" />
            {head.periods.map((p) => <th key={p} className="px-1 text-right font-normal">{p}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, s]) => s ? (
            <tr key={label} className="border-t border-line/60">
              <td className="py-1 pr-2">{label}</td>
              {s.values.map((v, i) => <td key={i} className="px-1 text-right">{v}</td>)}
            </tr>
          ) : null)}
        </tbody>
      </table>
    </div>
  );
}

export function Card({ c }: { c: CompanyCard }) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          {c.name ?? c.symbol} <span className="text-ink-3">· NSE: {c.symbol}{c.consolidated ? " · consolidated" : ""}</span>
        </PanelTitle>
      </PanelHeader>
      <div className="space-y-4 p-3" data-testid="nse-card">
        {c.about ? <p className="max-w-[80ch] text-[13px] text-ink-dim">{c.about}</p> : null}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" data-testid="nse-ratios">
          {c.ratios.map((r) => (
            <div key={r.name} className="rounded-lg border border-line p-2">
              <div className="text-[10px] uppercase tracking-wider text-ink-dim">{r.name}</div>
              <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">{r.value}</div>
            </div>
          ))}
        </div>
        {c.growth.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {c.growth.map((g) => (
              <div key={g.title} className="rounded-lg border border-line p-2">
                <div className="mb-1 text-[11px] font-semibold text-ink-2">{g.title}</div>
                {g.rows.map(([k, v]) => (
                  <div key={k} className="flex justify-between text-[12px] tabular-nums">
                    <span className="text-ink-3">{k.replace(/:$/, "")}</span><span>{v}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : null}
        <div className="grid gap-4 overflow-x-auto md:grid-cols-2">
          <SeriesTable title="Last 4 quarters (₹ Cr)" rows={[["Sales", c.quarters.Sales], ["Net profit", c.quarters["Net Profit"]]]} />
          <SeriesTable title="Yearly (₹ Cr)" rows={[["Sales", c.yearly.Sales], ["Net profit", c.yearly["Net Profit"]]]} />
          <SeriesTable title="Debt (₹ Cr)" rows={[["Borrowings", c.borrowings]]} />
          <SeriesTable title="Promoter holding" rows={[["Promoters", c.promoters]]} />
        </div>
        {c.pros.length || c.cons.length ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <ul className="space-y-1 text-[13px]">{c.pros.map((p) => <li key={p} className="text-up">+ {p}</li>)}</ul>
            <ul className="space-y-1 text-[13px]">{c.cons.map((p) => <li key={p} className="text-down">− {p}</li>)}</ul>
          </div>
        ) : null}
        <p className="text-[11px] text-ink-dim">
          Read live from{" "}
          <a href={c.url} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
            screener.in ↗
          </a>{" "}
          for your personal viewing; nothing is stored. Not investment advice.
        </p>
      </div>
    </Panel>
  );
}

function Arjun({ line, talking }: { line: string; talking: boolean }) {
  const box = portraitViewBox(ARJUN as CharacterDefinition, "bust");
  return (
    <div className="flex items-center gap-4" data-testid="nse-arjun">
      <svg viewBox={box} width={96} height={110} aria-hidden="true" className="shrink-0 overflow-visible">
        <RigDefs />
        <Character character={ARJUN as CharacterDefinition} pose={talking ? "talking_briefly" : "standing"}
                   emotion={talking ? "happy" : "neutral"} />
      </svg>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-ink">Arjun <span className="font-normal text-ink-3">· NSE analyst</span></div>
        <div className="mt-1 max-w-[60ch] rounded-lg border border-line bg-ink/[0.03] px-3 py-2 text-[13px] text-ink" data-testid="nse-say">
          {line}
        </div>
      </div>
    </div>
  );
}

function errorLine(e: unknown): string {
  const status = (e as { status?: number })?.status;
  if (status === 401 || status === 403) return "Sorry, I only work for Karthik. Sign in as admin to ask me.";
  const msg = (e as { message?: string })?.message;
  return msg && !/^Request failed/.test(msg) ? msg : "I couldn't reach screener.in just now. Try again in a minute.";
}

export function NseLabPage() {
  const [q, setQ] = useState("");
  const ask = useMutation({
    mutationFn: (query: string) =>
      api.get<CompanyCard>(`/labs/nse-desk/company?q=${encodeURIComponent(query)}`),
  });
  const line = ask.isPending
    ? `Reading ${q.trim()} on screener.in…`
    : ask.isError
      ? errorLine(ask.error)
      : ask.data
        ? `Here's ${ask.data.name ?? ask.data.symbol}, straight from its screener.in page.`
        : "Hi Karthik. Give me a company name or NSE symbol and I'll read its screener.in page for you.";
  return (
    <div className="min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-semibold">NSE Lab</h1>
        <p className="text-sm text-ink-3">Private to you. Arjun reads a company&apos;s screener.in page when you ask.</p>
      </div>
      <Panel>
        <div className="space-y-3 p-3">
          <Arjun line={line} talking={ask.isPending || !!ask.data} />
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate(q.trim()); }}
          >
            <label htmlFor="nse-q" className="sr-only">Company name or NSE symbol</label>
            <input
              id="nse-q" value={q} onChange={(e) => setQ(e.target.value)} maxLength={60}
              placeholder="e.g. RELIANCE, Tata Motors, INFY"
              className="min-w-0 flex-1 rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
            />
            <button type="submit" disabled={ask.isPending || !q.trim()}
                    className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-50">
              Ask Arjun
            </button>
          </form>
        </div>
      </Panel>
      {ask.data ? <Card c={ask.data} /> : null}
    </div>
  );
}
