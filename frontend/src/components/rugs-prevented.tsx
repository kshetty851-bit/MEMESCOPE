"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";

/**
 * RUGS PREVENTED (Karthik, 2026-10-02: "show this prevented rugs count ...
 * with nice box and animations"). The real wallet's money checks refuse a coin
 * linked to an earlier rug; this counts the refused coins that rugged within
 * five minutes anyway, from `/labs/graduation/rugs-prevented`. The same count
 * sits on Karthik's Lab (full) and the real wallet page (one line).
 */

export interface RugsPreventedData {
  since: string | null;
  refused: number;
  rugs_blocked: number;
  saved_per_wallet_usd: string;
  ticket_usd: string;
  last_rug: { symbol: string | null; at: string } | null;
  quiet_rugs_avoided: number;
  /** Set by the page, not the server: what "since" to print on the line. */
  since_label?: string;
}

/** `start`: count only from then (the real wallet page's partnership timer). */
export function useRugsPrevented(start?: string) {
  return useQuery({
    queryKey: ["graduation", "rugs-prevented", start ?? "all"],
    queryFn: () => api.get<RugsPreventedData>(
      `/labs/graduation/rugs-prevented${start ? `?start=${encodeURIComponent(start)}` : ""}`),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

function reducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/**
 * Counts up to `target` once on arrival, and again from the old figure when it
 * grows; `bumped` is true for a moment after a later rise, for the pulse.
 */
export function useCountUp(target: number, ms = 1200): { shown: number; bumped: boolean } {
  const [shown, setShown] = useState(() => (reducedMotion() ? target : 0));
  const [bumped, setBumped] = useState(false);
  const from = useRef(shown);
  const first = useRef(true);
  useEffect(() => {
    const start = from.current;
    const grew = !first.current && target > start;
    first.current = false;
    if (reducedMotion() || start === target) {
      from.current = target;
      setShown(target);
      return;
    }
    let frame = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms);
      const eased = 1 - (1 - p) ** 3;
      const value = Math.round(start + (target - start) * eased);
      from.current = value;
      setShown(value);
      if (p < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    let timer: number | undefined;
    if (grew) {
      setBumped(true);
      timer = window.setTimeout(() => setBumped(false), 2400);
    }
    return () => {
      cancelAnimationFrame(frame);
      if (timer) window.clearTimeout(timer);
    };
  }, [target, ms]);
  return { shown, bumped };
}

const money = (value: string | number) => {
  const n = Number(value);
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
};

const dubai = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Dubai", day: "numeric", month: "short" })
    .replace("Sept", "Sep");

function Shield({ live, size }: { live: boolean; size: number }) {
  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      {/* A soft ring, always on, and a brighter one for a moment after a new block. */}
      <span className="ambient absolute inset-0 rounded-full bg-up/25 animate-[pulse-ring_3s_ease-out_infinite]" />
      {live ? (
        <span className="absolute inset-0 rounded-full bg-up/50 animate-[pulse-ring_0.8s_ease-out_3]" />
      ) : null}
      <svg viewBox="0 0 24 24" aria-hidden="true"
           className="relative h-full w-full text-up drop-shadow-[0_0_6px_var(--color-up)]">
        <path fill="currentColor" fillOpacity={0.18} stroke="currentColor" strokeWidth={1.6}
              strokeLinejoin="round" d="M12 2.8 4.5 5.6v6.1c0 4.6 3.1 8.3 7.5 9.5 4.4-1.2 7.5-4.9 7.5-9.5V5.6z" />
        <path fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
              strokeLinejoin="round" d="m8.6 12.2 2.4 2.4 4.5-4.8" />
      </svg>
    </span>
  );
}

/** The full box, for Karthik's Lab. */
export function RugsPreventedCard({ data }: { data: RugsPreventedData | undefined }) {
  const { shown, bumped } = useCountUp(data?.rugs_blocked ?? 0);
  if (!data) return null;
  return (
    <div data-testid="rugs-prevented"
         className={`animate-rise relative overflow-hidden rounded-lg border p-4 transition-colors duration-700 ${
           bumped ? "border-up/70 bg-up/[0.08]" : "border-up/30 bg-up/[0.04]"}`}>
      <div className="flex items-center gap-4">
        <Shield live={bumped} size={44} />
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-semibold tabular-nums text-up" data-testid="rugs-prevented-count">
              {shown}
            </span>
            <span className="text-sm font-medium text-ink">rugs prevented</span>
          </div>
          <div className="text-xs text-ink-3">
            of {data.refused.toLocaleString("en-US")} coins the rug checks refused
            {data.since ? ` since ${dubai(data.since)}` : ""}
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border border-line bg-canvas/40 p-2">
          <div className="text-base font-semibold tabular-nums text-up">
            {money(data.saved_per_wallet_usd)}
          </div>
          <div className="text-ink-3">kept per {money(data.ticket_usd)}-a-trade wallet</div>
        </div>
        <div className="rounded-md border border-line bg-canvas/40 p-2">
          <div className="text-base font-semibold tabular-nums text-ink">
            +{data.quiet_rugs_avoided}
          </div>
          <div className="text-ink-3">more avoided by the quiet rule</div>
        </div>
      </div>
      {data.last_rug ? (
        <div className="mt-2 text-[11px] text-ink-3">
          Last one stopped: <b className="text-ink-2">{data.last_rug.symbol ?? "a coin"}</b>,{" "}
          {dubai(data.last_rug.at)}
        </div>
      ) : null}
    </div>
  );
}

/** One line, for the real wallet page. */
export function RugsPreventedLine({ data }: { data: RugsPreventedData | undefined }) {
  const { shown, bumped } = useCountUp(data?.rugs_blocked ?? 0);
  if (!data) return null;
  return (
    <div data-testid="rugs-prevented-line"
         className={`animate-rise mt-4 flex items-center gap-3 rounded-lg border px-3 py-2 transition-colors duration-700 ${
           bumped ? "border-up/70 bg-up/[0.08]" : "border-up/30 bg-up/[0.04]"}`}>
      <Shield live={bumped} size={26} />
      <p className="text-sm text-ink-2">
        <span className="text-lg font-semibold tabular-nums text-up">{shown}</span>{" "}
        rugs prevented{data.since_label ? ` since ${data.since_label}` : ""}
        <span className="text-ink-3">
          {" "}· {money(data.saved_per_wallet_usd)} kept per {money(data.ticket_usd)}-a-trade wallet
        </span>
      </p>
    </div>
  );
}

export function RugsPreventedLive({ compact = false, start }: {
  compact?: boolean;
  /** Count from here; the line also says so ("since the timer started"). */
  start?: string;
}) {
  const q = useRugsPrevented(start);
  if (!compact) return <RugsPreventedCard data={q.data} />;
  return (
    <RugsPreventedLine
      data={q.data && { ...q.data, since_label: start ? "the timer started" : undefined }} />
  );
}
