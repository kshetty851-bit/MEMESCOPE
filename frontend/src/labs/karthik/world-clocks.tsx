"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Two analog clocks, UAE and USA (Karthik, 2026-10-04: "put 2 stylish
 * animation analog clock for UAE and USA in karthik lab"). The USA one is New
 * York: US evening is when most coins graduate. Daylight saving is the
 * browser's `Intl` time-zone data, so it moves by itself.
 */
const ZONES = [
  { id: "uae", city: "Dubai", country: "UAE", tz: "Asia/Dubai" },
  { id: "usa", city: "New York", country: "USA", tz: "America/New_York" },
] as const;

const FORMATS = new Map<string, Intl.DateTimeFormat>();

/** Hours, minutes, seconds and weekday in a time zone. */
export function zoneTime(tz: string, at: Date) {
  let f = FORMATS.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz, hourCycle: "h23", weekday: "short",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    FORMATS.set(tz, f);
  }
  const p = Object.fromEntries(f.formatToParts(at).map((x) => [x.type, x.value]));
  return { h: Number(p.hour), m: Number(p.minute), s: Number(p.second), day: p.weekday ?? "" };
}

/** Hand angles in degrees, 12 o'clock = 0. `s` may carry a fraction (the sweep). */
export function handAngles(h: number, m: number, s: number) {
  return { hour: ((h % 12) + m / 60 + s / 3600) * 30, minute: (m + s / 60) * 6, second: s * 6 };
}

/** How many hours `tz` is behind Dubai right now (whole or half hours). */
function hoursBehindDubai(tz: string, at: Date): number {
  const a = zoneTime("Asia/Dubai", at);
  const b = zoneTime(tz, at);
  const diff = (((a.h * 60 + a.m) - (b.h * 60 + b.m)) % 1440 + 1440) % 1440;
  return Math.round(diff / 30) / 2;
}

function AnalogClock({ zone }: { zone: (typeof ZONES)[number] }) {
  const hour = useRef<SVGLineElement>(null);
  const minute = useRef<SVGLineElement>(null);
  const second = useRef<SVGGElement>(null);
  const [label, setLabel] = useState<{ time: string; day: string; night: boolean; behind: number } | null>(null);

  useEffect(() => {
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let shown = -1;
    const draw = () => {
      const now = new Date();
      const t = zoneTime(zone.tz, now);
      const s = t.s + (smooth ? now.getMilliseconds() / 1000 : 0);
      const a = handAngles(t.h, t.m, s);
      hour.current?.setAttribute("transform", `rotate(${a.hour} 50 50)`);
      minute.current?.setAttribute("transform", `rotate(${a.minute} 50 50)`);
      second.current?.setAttribute("transform", `rotate(${a.second} 50 50)`);
      if (t.s !== shown) {
        shown = t.s;
        const pad = (n: number) => String(n).padStart(2, "0");
        setLabel({
          time: `${pad(t.h)}:${pad(t.m)}:${pad(t.s)}`, day: t.day,
          night: t.h < 6 || t.h >= 18, behind: hoursBehindDubai(zone.tz, now),
        });
      }
      frame = smooth ? requestAnimationFrame(draw) : window.setTimeout(draw, 250);
    };
    draw();
    return () => (smooth ? cancelAnimationFrame(frame) : window.clearTimeout(frame));
  }, [zone.tz]);

  return (
    <div className="wclock flex items-center gap-3 rounded-xl border border-line bg-ink/[0.02] p-3" data-testid={`clock-${zone.id}`}>
      <svg viewBox="0 0 100 100" width={112} height={112} role="img"
           aria-label={label ? `${zone.city} ${label.time}` : `${zone.city} clock`} className="shrink-0">
        <defs>
          <radialGradient id={`wclock-face-${zone.id}`} cx="50%" cy="38%" r="65%">
            <stop offset="0%" stopColor="var(--color-raised)" />
            <stop offset="100%" stopColor="var(--color-sunken)" />
          </radialGradient>
          <filter id={`wclock-glow-${zone.id}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="1.2" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <circle cx="50" cy="50" r="48" fill="none" stroke="var(--color-accent)" strokeOpacity="0.35" strokeWidth="1.5" className="wclock-ring" />
        <circle cx="50" cy="50" r="45" fill={`url(#wclock-face-${zone.id})`} stroke="var(--color-line)" strokeWidth="1" />
        {Array.from({ length: 60 }, (_, i) => {
          const major = i % 5 === 0;
          return (
            <line key={i} x1="50" y1={major ? 9 : 10.5} x2="50" y2={major ? 15 : 12.5}
                  stroke={major ? "var(--color-ink-2)" : "var(--color-ink-4)"}
                  strokeWidth={major ? 1.6 : 0.6} strokeLinecap="round"
                  transform={`rotate(${i * 6} 50 50)`} />
          );
        })}
        {[["12", 50, 25.5], ["3", 76.5, 52.5], ["6", 50, 79.5], ["9", 23.5, 52.5]].map(([n, x, y]) => (
          <text key={n} x={x} y={y} textAnchor="middle" fontSize="7.5" fontWeight="600"
                fill="var(--color-ink-3)" style={{ fontVariantNumeric: "tabular-nums" }}>{n}</text>
        ))}
        {label ? (
          <>
            <line ref={hour} x1="50" y1="53" x2="50" y2="29" stroke="var(--color-ink)" strokeWidth="3.4" strokeLinecap="round" />
            <line ref={minute} x1="50" y1="54" x2="50" y2="18" stroke="var(--color-ink)" strokeWidth="2.2" strokeLinecap="round" />
            <g ref={second} filter={`url(#wclock-glow-${zone.id})`}>
              <line x1="50" y1="58" x2="50" y2="14" stroke="var(--color-accent)" strokeWidth="1" strokeLinecap="round" />
              <circle cx="50" cy="14" r="1.6" fill="var(--color-accent)" />
            </g>
          </>
        ) : null}
        <circle cx="50" cy="50" r="3" fill="var(--color-accent)" />
        <circle cx="50" cy="50" r="1.2" fill="var(--color-sunken)" />
      </svg>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-ink-3">
          {zone.country} · {zone.city}
        </div>
        <div className="text-2xl font-semibold tabular-nums text-ink">{label?.time ?? "--:--:--"}</div>
        <div className="text-[11px] text-ink-3">
          {label ? (
            <>
              <span aria-hidden="true">{label.night ? "☾" : "☀"}</span> {label.day}
              {label.behind ? ` · ${label.behind}h behind Dubai` : ""}
            </>
          ) : " "}
        </div>
      </div>
    </div>
  );
}

export function WorldClocks() {
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="world-clocks">
      {ZONES.map((z) => <AnalogClock key={z.id} zone={z} />)}
    </div>
  );
}
