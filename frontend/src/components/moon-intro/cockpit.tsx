"use client";

import "./cockpit.css";

import type { CSSProperties } from "react";

import {
  RADIO,
  REDUCED_TIMELINE,
  SHORT_TIMELINE,
  SWITCHES,
  TIMELINE,
  WARP_READOUTS,
  type IntroPhase,
} from "./timeline";

/**
 * The cockpit frame + HUD. No clock of its own: every change here is a prop
 * change (phase, `passed` moments), and all in-phase motion is CSS keyed off
 * `data-phase` and `--mi-d` (this phase's length in seconds), plus `--mi-p`
 * inherited from the controller's `.mi-root` for the reveal progress bar.
 */
export type CockpitProps = {
  phase: IntroPhase;
  mode: "full" | "short" | "reduced";
  /** Moment keys already passed: `${phase}.${name}` or `${phase}.${name}.${i}`. */
  passed: ReadonlySet<string>;
  soundOn: boolean;
  onToggleSound: () => void;
  onSkip: () => void;
};

const ORDER: IntroPhase[] = [
  "seatbelt",
  "cockpit",
  "ignition",
  "warp",
  "approach",
  "landing",
  "reveal",
  "done",
];
const TIMELINES = {
  full: TIMELINE,
  short: SHORT_TIMELINE,
  reduced: REDUCED_TIMELINE,
} as const;
const idx = (p: IntroPhase) => ORDER.indexOf(p);

export function Cockpit({
  phase,
  mode,
  passed,
  soundOn,
  onToggleSound,
  onSkip,
}: CockpitProps) {
  const tl = TIMELINES[mode];
  const at = idx(phase);
  const has = (k: string) => passed.has(k);
  const count = (prefix: string, n: number) =>
    Array.from({ length: n }, (_, i) => i).filter((i) => has(`${prefix}.${i}`)).length;

  const dur = tl.find(([name]) => name === phase)?.[1] ?? 1;
  // The seatbelt card stays one phase longer so it can fade out over the frame.
  const beltOn =
    phase === "seatbelt" || (tl[0]?.[0] === "seatbelt" && tl[1]?.[0] === phase);
  const frameOn = at >= idx("cockpit");
  const booted = has("cockpit.hudBoot") || at > idx("cockpit");
  const beeps = count("ignition.beeps", 3);
  const step = at > idx("warp") ? 3 : Math.max(0, count("warp.velocity", 4) - 1);
  const nearMiss = phase === "approach" && has("approach.nearMiss");
  const repaired = has("approach.repaired");
  const locked = has("approach.lock");

  const status = has("landing.eagle")
    ? "Landed"
    : locked
      ? "Target acquired"
      : has("seatbelt.secured")
        ? "Seatbelt secured"
        : "";

  const style = { "--mi-d": `${dur}s` } as CSSProperties;

  let screen;
  if (phase === "cockpit") screen = <span className="mi-dim">PRE-FLIGHT CHECK</span>;
  else if (phase === "ignition")
    screen = has("ignition.throttle") ? (
      <span key="go" className="mi-digit mi-go">
        LIFTOFF
      </span>
    ) : (
      <span key={beeps} className="mi-digit">
        {beeps ? 4 - beeps : "·"}
      </span>
    );
  else
    screen = (
      <dl className="mi-readouts">
        <dt>VELOCITY</dt>
        <dd key={`v${step}`}>{WARP_READOUTS.velocity[step]}</dd>
        <dt>ALTITUDE (MCAP)</dt>
        <dd key={`m${step}`}>{WARP_READOUTS.mcap[step]}</dd>
        <dt>FUEL: HOPIUM</dt>
        <dd>100%</dd>
      </dl>
    );

  return (
    <div
      className="mi-cockpit"
      role="presentation"
      data-phase={phase}
      data-mode={mode}
      style={style}
    >
      {frameOn && (
        <div
          className="mi-frame"
          aria-hidden="true"
          data-dolly={has("reveal.dolly") || phase === "done" || undefined}
        >
          <svg
            className="mi-strut mi-strut--l"
            viewBox="0 0 100 1000"
            preserveAspectRatio="none"
          >
            <path d="M0 0H70L100 1000H0Z" />
            <path className="mi-edge" d="M70 0L100 1000" />
          </svg>
          <svg
            className="mi-strut mi-strut--r"
            viewBox="0 0 100 1000"
            preserveAspectRatio="none"
          >
            <path d="M100 0H30L0 1000H100Z" />
            <path className="mi-edge" d="M30 0L0 1000" />
          </svg>

          <div className="mi-overhead">
            <ul className="mi-switches">
              {SWITCHES.map(([label, value], i) => {
                const on = has(`cockpit.switches.${i}`) || at > idx("cockpit");
                return (
                  <li
                    key={label}
                    className="mi-switch"
                    data-on={on || undefined}
                    data-bad={value === "DISABLED" || undefined}
                  >
                    <svg viewBox="0 0 18 30">
                      <rect
                        x="3"
                        y="6"
                        width="12"
                        height="18"
                        rx="3"
                        className="mi-socket"
                      />
                      <line x1="9" y1="15" x2="9" y2="4" className="mi-lever" />
                      <circle cx="9" cy="28" r="2" className="mi-led-off" />
                      <circle cx="9" cy="28" r="2" className="mi-led" />
                    </svg>
                    <span>
                      {label}: {on ? value : "---"}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="mi-canopy">
            {booted && (
              <>
                <div className="mi-scan" />
                <p className="mi-hud-title">
                  MEMESCOPE FLIGHT SYSTEMS v4.20 — ALL SYSTEMS PUMPING
                </p>
              </>
            )}
            {phase === "approach" && (
              <div className="mi-target" data-lock={locked || undefined}>
                <svg className="mi-reticle" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="30" />
                  <circle cx="50" cy="50" r="3" />
                  <path d="M50 8V22M50 78V92M8 50H22M78 50H92M14 26V14H26M74 14H86V26M86 74V86H74M26 86H14V74" />
                </svg>
                {locked && <p className="mi-ok">TARGET ACQUIRED: THE MOON</p>}
                {nearMiss && !repaired && <p className="mi-alarm">HULL BREACH</p>}
                {nearMiss && repaired && !locked && (
                  <p className="mi-ok mi-pop">AUTO-REPAIR ✓</p>
                )}
              </div>
            )}
            {phase === "landing" && has("landing.eagle") && (
              <p className="mi-eagle">THE EAGLE HAS LANDED 🌕</p>
            )}
            {at >= idx("reveal") && (
              <div className="mi-console">
                <h2>LANDING CONSOLE</h2>
                <p>Docking with Karthik&apos;s Lab…</p>
                <div className="mi-bar">
                  <i />
                </div>
              </div>
            )}
          </div>

          <div className="mi-dash" data-hot={at >= idx("ignition") || undefined}>
            <div className="mi-gauges">
              {["THRUST", "HYPE"].map((g) => (
                <figure key={g} className="mi-gauge">
                  <svg viewBox="0 0 60 40">
                    <path d="M6 36A24 24 0 0 1 54 36" className="mi-arc" />
                    <path d="M42 15A24 24 0 0 1 54 36" className="mi-arc mi-arc--hot" />
                    <line x1="30" y1="36" x2="30" y2="15" className="mi-needle" />
                  </svg>
                  <figcaption>{g}</figcaption>
                </figure>
              ))}
            </div>
            <div className="mi-screen">{screen}</div>
            <svg
              className="mi-throttle"
              viewBox="0 0 40 80"
              data-fwd={has("ignition.throttle") || at > idx("ignition") || undefined}
            >
              <rect x="16" y="8" width="8" height="64" rx="4" className="mi-socket" />
              <g className="mi-handle">
                <line x1="20" y1="60" x2="20" y2="48" />
                <rect x="6" y="40" width="28" height="10" rx="5" />
              </g>
            </svg>
            {at >= idx("warp") && at <= idx("landing") && (
              <div className="mi-radio">
                <b>◉ RADIO</b>
                <div className="mi-radio-clip">
                  <div className="mi-radio-track">
                    {[0, 1, 2, 3].map((n) =>
                      RADIO.map((line) => <span key={`${n}${line}`}>{line}</span>),
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {nearMiss && (
        <div className="mi-crack" aria-hidden="true" data-fixed={repaired || undefined}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M68 38L80 20L86 4M68 38L92 34L100 41M68 38L74 62L70 84M68 38L50 48L30 46M68 38L57 22L53 6M74 62L85 71M50 48L44 61M80 20L90 17" />
            <circle cx="68" cy="38" r="1.6" />
          </svg>
        </div>
      )}

      {beltOn && (
        <div className="mi-belt" aria-hidden="true">
          <div className="mi-stripes mi-stripes--t" />
          <div className="mi-stripes mi-stripes--b" />
          <svg
            className="mi-buckle"
            viewBox="0 0 120 40"
            data-shut={has("seatbelt.buckle") || undefined}
          >
            <rect x="0" y="15" width="40" height="10" className="mi-strap" />
            <rect x="96" y="15" width="24" height="10" className="mi-strap" />
            <rect className="mi-tongue" x="30" y="11" width="36" height="18" rx="3" />
            <rect x="58" y="6" width="42" height="28" rx="7" className="mi-latch" />
            <rect x="68" y="16" width="22" height="8" rx="2" className="mi-latch-btn" />
          </svg>
          {has("seatbelt.secured") ? (
            <p className="mi-belt-text mi-secured">SECURED ✓</p>
          ) : (
            <p className="mi-belt-text">
              <span className="mi-type">FASTEN YOUR SEATBELT</span>
              <span className="mi-caret" />
            </p>
          )}
        </div>
      )}

      <div className="mi-controls">
        {at < idx("reveal") && (
          <button type="button" className="mi-btn" onClick={onSkip}>
            SKIP TO MOON <span aria-hidden="true">⏭</span>
          </button>
        )}
        <button
          type="button"
          className="mi-btn mi-btn--icon"
          aria-pressed={soundOn}
          aria-label={soundOn ? "Sound on" : "Sound off"}
          onClick={onToggleSound}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
            <path d="M4 9H8L13 5V19L8 15H4Z" fill="currentColor" />
            <path
              d={
                soundOn
                  ? "M16 9C17.5 10.5 17.5 13.5 16 15M18.5 6.5C21.5 9.5 21.5 14.5 18.5 17.5"
                  : "M16 9L22 15M22 9L16 15"
              }
            />
          </svg>
        </button>
      </div>

      <p role="status" className="mi-sr">
        {status}
      </p>
    </div>
  );
}
