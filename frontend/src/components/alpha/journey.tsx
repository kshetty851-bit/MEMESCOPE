"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { DayLog, type LogDay } from "@/components/alpha/journey-log";
import { api } from "@/lib/api-client";

/**
 * THE MEMESCOPE JOURNEY — "Built through failure" (Karthik, 2026-09-27).
 *
 * An ADDED section: it sits between "What runs here" and the footer and
 * touches nothing else on the page. Every figure on it is live, from
 * `/journey` (public, cached a minute server-side; GitHub
 * counts ten): commits, merged PRs, strategies and trades tested, Karthik's
 * Lab headline, and today's real-wallet trade/win COUNTS. The only fixed
 * facts are the first commit's date and the words.
 */

interface Journey {
  lab: {
    started_at: string;
    judge_at: string;
    trades: number;
    wins: number;
    rugs: number;
    finished_days: number;
    last_day_pnl_usd: string | null;
  };
  real_today: { trades: number; wins: number; since: string };
  strategies_tested: number;
  trades_tested: number;
  graduations_watched: number;
  commits: number | null;
  merged_prs: number | null;
  days?: LogDay[];
}

/** The first commit: "Day 1 Foundation Complete". */
const FIRST_COMMIT = new Date("2026-07-27T00:00:00+04:00");
const DAY_MS = 86_400_000;

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "27 SEP 2026", in Dubai. */
export function dubaiDate(at: Date | string): string {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Dubai" })
    .format(new Date(at)).split("-").map(Number) as [number, number, number];
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

/** Whole calendar months since the first commit, in Dubai. */
export function monthsSince(start: Date, now: Date): number {
  const fmt = (d: Date) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Dubai" }).format(d).split("-").map(Number);
  const [y0, m0, d0] = fmt(start) as [number, number, number];
  const [y1, m1, d1] = fmt(now) as [number, number, number];
  return Math.max(0, (y1 - y0) * 12 + (m1 - m0) - (d1 < d0 ? 1 : 0));
}

const WORDS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE"];

/** "~4½" — days to the nearest half. */
export function halfDays(fromIso: string, now: number): string {
  const halves = Math.round(((now - new Date(fromIso).getTime()) / DAY_MS) * 2);
  const whole = Math.floor(halves / 2);
  return `~${whole}${halves % 2 ? "½" : ""}`;
}

function money(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  return `${n < 0 ? "−" : "+"}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/** True once the element has scrolled into view (and stays true). */
function useSeen<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, seen];
}

function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  return (
    <div ref={ref} className={`journey-reveal ${seen ? "is-seen" : ""} ${className}`}>
      {children}
    </div>
  );
}

/** Counts up to `value` once on screen; a still number for reduced motion. */
function Counter({ value }: { value: number | null }) {
  const [ref, seen] = useSeen<HTMLSpanElement>();
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (!seen || value === null) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / 1200);
      setShown(Math.round(value * (1 - (1 - p) ** 3)));
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [seen, value]);
  return (
    <span ref={ref} className="tabular-nums">
      {value === null ? "—" : shown.toLocaleString("en-US")}
    </span>
  );
}

const BUILT = ["Token discovery", "Market data", "Smart-money signals", "Liquidity analysis", "Risk analysis",
  "Graduation tracking", "Paper trading", "Strategy testing", "Execution infrastructure"];
const TESTED = ["Entry conditions", "Market-cap ranges", "Liquidity conditions", "Take-profit structures",
  "Exit rules", "Position sizes", "Holding periods", "Dead-token handling"];

function Chips({ items }: { items: string[] }) {
  return (
    <ul className="mt-4 flex flex-wrap gap-2">
      {items.map((item) => (
        <li key={item} className="journey-chip">{item}</li>
      ))}
    </ul>
  );
}

function Terminal({ lines }: { lines: string[] }) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  return (
    <div ref={ref} className={`journey-terminal ${seen ? "is-seen" : ""}`} aria-label="Research log">
      {lines.map((line, i) => (
        <p key={line} style={{ animationDelay: `${i * 420}ms` }}>
          <span className="text-accent">&gt;</span> {line}
        </p>
      ))}
      <span className="journey-cursor" aria-hidden />
    </div>
  );
}

export function Journey() {
  const [data, setData] = useState<Journey | null>(null);
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    const read = () => {
      setNow(Date.now());
      api
        .get<Journey>("/journey", { skipAuthRetry: true })
        .then((d) => live && setData(d))
        .catch(() => {
          // The story reads without its figures; a failed read is not news.
        });
    };
    read();
    const timer = window.setInterval(read, 60_000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const today = now === null ? null : new Date(now);
  const months = today ? monthsSince(FIRST_COMMIT, today) : null;
  const monthsWord = months === null ? "" : (WORDS[months] ?? String(months));
  const lab = data?.lab;
  const real = data?.real_today;

  return (
    <section aria-labelledby="journey-heading" className="journey">
      <Reveal>
        <p className="text-label text-accent">The MEMESCOPE journey</p>
        <h2 id="journey-heading" className="journey-title">Built through failure.</h2>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-ink-2">
          MEMESCOPE wasn&apos;t built because the first strategy worked.
          <br />
          It was built because most strategies didn&apos;t.
        </p>
        <div className="journey-span">
          <p className="whitespace-nowrap font-mono text-base text-ink sm:text-xl">
            27 JUL 2026 <span className="text-accent">→</span> {today ? dubaiDate(today) : "TODAY"}
          </p>
          {months !== null ? (
            <p className="mt-1 text-label text-ink-3">
              {monthsWord} {months === 1 ? "month" : "months"} of building, testing &amp; learning
            </p>
          ) : null}
        </div>
      </Reveal>

      {/* PROJECT SCALE */}
      <Reveal>
        <dl className="journey-stats">
          <div className="journey-card">
            <dt className="text-label text-ink-3">Commits</dt>
            <dd className="journey-stat"><Counter value={data?.commits ?? null} /></dd>
          </div>
          <div className="journey-card">
            <dt className="text-label text-ink-3">Merged PRs</dt>
            <dd className="journey-stat"><Counter value={data?.merged_prs ?? null} /></dd>
          </div>
          <div className="journey-card">
            <dt className="text-label text-ink-3">Strategy experiments</dt>
            <dd className="journey-stat">
              <Counter value={data?.strategies_tested ?? null} />
              {data ? "+" : ""}
            </dd>
          </div>
          <div className="journey-card">
            <dt className="text-label text-ink-3">Trades &amp; observations</dt>
            <dd className="journey-stat"><Counter value={data?.trades_tested ?? null} /></dd>
            {data ? (
              <p className="mt-1 text-xs text-ink-3">
                trades tested · {data.graduations_watched.toLocaleString("en-US")} graduations watched
              </p>
            ) : null}
          </div>
        </dl>
      </Reveal>

      {/* TIMELINE */}
      <ol className="journey-timeline">
        <li className="journey-step">
          <Reveal>
            <p className="journey-tag">27 JUL 2026</p>
            <div className="journey-card">
              <h3 className="journey-h3">Project initialized</h3>
              <p className="mt-1 text-sm text-ink">MEMESCOPE begins.</p>
              <p className="mt-2 text-sm leading-relaxed text-ink-2">
                An idea to build an AI-powered memecoin research and scanning system capable of
                identifying opportunities while systematically measuring whether those signals
                actually have an edge.
              </p>
            </div>
          </Reveal>
        </li>

        <li className="journey-step">
          <Reveal>
            <p className="journey-tag">Build</p>
            <div className="journey-card">
              <h3 className="journey-h3">The scanner became a laboratory</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-2">
                MEMESCOPE evolved into a full research environment involving:
              </p>
              <Chips items={BUILT} />
            </div>
          </Reveal>
        </li>

        <li className="journey-step journey-step--lesson">
          <Reveal>
            <p className="journey-tag text-down">First hard lesson</p>
            <div className="journey-card journey-card--lesson">
              <h3 className="journey-lesson">No strategy currently has adequate edge.</h3>
              <p className="mt-3 text-sm leading-relaxed text-ink-2">
                This was an important milestone. MEMESCOPE didn&apos;t hide the result.
                <br />
                It recorded it.
              </p>
              <p className="mt-3 font-mono text-xs tracking-[0.16em] text-down">FAILURE WAS DATA.</p>
            </div>
          </Reveal>
        </li>

        <li className="journey-step">
          <Reveal>
            <p className="journey-tag">Strategy lab</p>
            <div className="journey-card">
              <h3 className="journey-h3">Test. Reject. Learn. Repeat.</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-2">
                Multiple strategy families were tested with different:
              </p>
              <Chips items={TESTED} />
              <p className="mt-4 text-sm leading-relaxed text-ink-2">
                The objective was not to make a backtest look profitable.
                <br />
                <span className="text-ink">The objective was to discover what survives testing.</span>
              </p>
            </div>
          </Reveal>
        </li>

        <li className="journey-step journey-step--now">
          <Reveal>
            <p className="journey-tag text-up">Current breakthrough</p>
            <div className="journey-card journey-card--now">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="journey-now-title">And then something finally started to work.</h3>
                <span className="journey-badge">Early signal — not proven</span>
              </div>
              <div className="journey-now-stats">
                <div>
                  <p className="journey-stat"><Counter value={lab?.finished_days ?? null} /></p>
                  <p className="text-label text-ink-3">Finished days</p>
                </div>
                <div>
                  <p className="journey-stat">
                    <Counter value={lab?.wins ?? null} />
                    <span className="text-ink-3"> / </span>
                    <Counter value={lab?.trades ?? null} />
                  </p>
                  <p className="text-label text-ink-3">Wins / trades</p>
                </div>
                <div>
                  <p className={`journey-stat ${Number(lab?.last_day_pnl_usd ?? 0) < 0 ? "text-down" : "text-up"}`}>
                    {lab ? money(lab.last_day_pnl_usd) : "—"}
                  </p>
                  <p className="text-label text-ink-3">Last finished day</p>
                </div>
              </div>
              <p className="mt-4 text-sm leading-relaxed text-ink-2">
                After multiple failed strategies, one rule set began producing results worth
                investigating. But {lab ? `${lab.finished_days} finished day${lab.finished_days === 1 ? "" : "s"}` : "a few days"} is
                not enough to declare an edge proven.
              </p>
              <p className="mt-2 text-xs text-ink-3">Karthik&apos;s Lab, paper money · live</p>
            </div>
          </Reveal>
        </li>

        <li className="journey-step">
          <Reveal>
            <p className="journey-tag">Paper → Real</p>
            <div className="journey-card">
              <p className="journey-stat">
                <Counter value={real?.wins ?? null} />
                <span className="text-ink-3"> / </span>
                <Counter value={real?.trades ?? null} />
              </p>
              <p className="text-label text-ink-3">Real-wallet wins today (Dubai)</p>
              {real && real.trades === 0 ? (
                <p className="mt-1 text-xs text-ink-3">No real trades yet today.</p>
              ) : null}
              <p className="mt-3 text-sm leading-relaxed text-ink-2">
                Real execution is being compared against the laboratory assumptions, including
                fills and execution behavior.
              </p>
              <p className="mt-3 font-mono text-[11px] tracking-[0.14em] text-warn">
                REAL MONEY REMAINS LIMITED AND EXPERIMENTAL.
              </p>
            </div>
          </Reveal>
        </li>
      </ol>

      {/* THE DAY-BY-DAY LOG — grows by itself from each day's commits */}
      <Reveal className="mt-10">
        <DayLog days={data?.days} />
      </Reveal>

      {/* WHAT WE STILL DON'T KNOW */}
      <Reveal>
        <div className="journey-card journey-unknowns">
          <p className="text-label text-warn">What we still don&apos;t know</p>
          <ol className="mt-4 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {[
              [`Only ${lab && now !== null ? halfDays(lab.started_at, now) : "a few"} days`,
                "The current rule is still very young."],
              ["The $75k threshold was discovered from the results",
                "It wasn't a completely blind hypothesis. Future trades provide the cleaner test."],
              ["Zero rugs ≠ zero risk", "A single rug can materially affect a small sample."],
              ["Larger positions are unproven",
                "$50 trades working does not automatically mean $200 trades will execute equally well."],
              ["Earlier strategies also looked good at first",
                "Some previous strategies later failed. That is why the current one remains under validation."],
            ].map(([head, body], i) => (
              <li key={head} className="flex gap-3">
                <span className="font-mono text-sm text-warn">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <p className="text-sm font-medium uppercase tracking-wide text-ink">{head}</p>
                  <p className="mt-1 text-sm leading-relaxed text-ink-2">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Reveal>

      {/* THE HUMAN STORY + STATUS */}
      <div className="journey-pair">
        <Reveal>
          <div className="journey-card h-full">
            <h3 className="journey-h3">
              {monthsWord ? `${monthsWord} months. ` : ""}
              {data?.commits ? `${data.commits.toLocaleString("en-US")} commits. ` : ""}A lot of dead ends.
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              MEMESCOPE wasn&apos;t built in a weekend. It was built through late nights, broken
              assumptions, failed strategies, infrastructure problems, bad data, backtests that
              didn&apos;t survive reality, and countless small improvements.
            </p>
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Every failed experiment removed one more possibility. The goal was never to make a
              chart look good. The goal was to find out what actually survives.
            </p>
            <Terminal
              lines={[
                "experiments_failed: MANY",
                "shortcuts_taken: 0",
                "edge_proven: NOT_YET",
                "research_continues: TRUE",
              ]}
            />
          </div>
        </Reveal>
        <Reveal>
          <div className="journey-card h-full">
            <p className="text-label text-accent">MEMESCOPE status</p>
            <dl className="journey-status">
              {[
                ["Research phase", "ACTIVE", "text-up"],
                ["Current strategy", "UNDER VALIDATION", "text-warn"],
                ["Real money", "LIMITED", "text-warn"],
                ["Edge", "UNPROVEN", "text-down"],
                ["Next checkpoint", lab ? dubaiDate(lab.judge_at) : "—", "text-accent"],
              ].map(([k, v, tone]) => (
                <div key={k}>
                  <dt className="text-sm text-ink-2">{k}</dt>
                  <dd className={`font-mono text-sm ${tone}`}>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </Reveal>
      </div>

      {/* FINAL LINE */}
      <Reveal className="journey-final">
        <p className="journey-title">We&apos;re not done.</p>
        <p className="mt-4 text-base leading-relaxed text-ink-2">
          One good week doesn&apos;t prove an edge.
          <br />
          One bad week doesn&apos;t kill the research.
          <br />
          <span className="text-ink">MEMESCOPE keeps testing.</span>
        </p>
        <p className="mt-4 text-sm leading-relaxed text-ink-3">
          Because the objective isn&apos;t to find a strategy that looks good.
          <br />
          It&apos;s to find one that survives.
        </p>
      </Reveal>
    </section>
  );
}
