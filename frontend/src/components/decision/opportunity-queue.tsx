"use client";

import Link from "next/link";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import { CloneRiskBadge } from "@/components/decision/clone-risk-badge";
import { ConvictionBadge } from "@/components/decision/conviction-badge";
import { CONVICTION_LABEL, type Conviction } from "@/lib/conviction";
import { MISSION_LABEL, MISSION_MEANING, MISSION_RULE, type MissionState, MISSION_TONE } from "@/lib/mission";
import {
  PRIORITY_LABEL,
  PRIORITY_MEANING,
  PRIORITY_TONE,
  type PriorityResult,
} from "@/lib/research-priority";
import { cn } from "@/lib/utils";
import type { Change } from "@/lib/changes";
import type { TokenIdentity } from "@/types/identity";
import type { ScoreGrade } from "@/types/score";

/**
 * The Opportunity Queue — a work list, not a leaderboard.
 *
 * A leaderboard answers "what is winning". This answers "what should you look
 * at first", and the two orders are genuinely different: a token that just got
 * vetoed sits at the top here and would not appear on a leaderboard at all.
 *
 * Ordering is by research value, so the queue is not sorted by return, market
 * cap or score. Every card states its priority, the one sentence that earned
 * it, and the arithmetic behind that placement.
 *
 * When nothing qualifies the queue says so and shows nothing. Padding it with
 * the least-bad options available would be exactly the behaviour that makes a
 * briefing worthless.
 */

export interface QueueItem {
  mint: string;
  name?: string | null;
  symbol?: string | null;
  grade?: ScoreGrade | null;
  isElite?: boolean;
  score?: string | null;
  conviction: Conviction | null;
  mission: MissionState;
  priority: PriorityResult;
  confidence: number | null;
  changes: Change[];
  identity?: TokenIdentity;
}

export function OpportunityQueue({ items }: { items: QueueItem[] }) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-lg font-medium tracking-tight text-ink">Opportunity queue</h2>
          <Why>
            Ordered by where an hour of research is likely to pay, not by return
            or score. A deteriorating project can outrank a healthy one — an
            unexamined risk is the expensive kind, and LETZMOON has no view on
            whether you should hold, buy or sell anything.
          </Why>
        </div>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
          If you have time for three projects today, these are the three.
        </p>
      </header>

      {items.length === 0 ? (
        <Panel density="compact">
          <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
            No project clears the bar for research attention today. That is the
            reading — the queue stays empty rather than padding itself with the
            least-bad options on the board.
          </p>
        </Panel>
      ) : (
        <ol className="flex flex-col gap-3">
          {items.map((item, index) => (
            <QueueCard key={item.mint} item={item} rank={index + 1} />
          ))}
        </ol>
      )}
    </section>
  );
}

function QueueCard({ item, rank }: { item: QueueItem; rank: number }) {
  const { priority } = item;

  return (
    <li>
      <Panel density="compact" className="lm-lift flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-baseline gap-3">
            <span data-numeric className="font-mono text-sm text-ink-faint">
              {String(rank).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <Link
                href={`/tokens/${item.mint}`}
                className="truncate text-base font-medium text-ink hover:text-brand"
              >
                {item.symbol ?? item.name ?? (
                  <span className="font-mono">
                    {item.mint.slice(0, 4)}…{item.mint.slice(-4)}
                  </span>
                )}
              </Link>
              {item.name && item.symbol && item.name !== item.symbol ? (
                <p className="truncate text-xs text-ink-faint">{item.name}</p>
              ) : null}
              {/* Two rows can legitimately carry the same symbol — different
                  mints, one name. Without this the queue looks duplicated and
                  the user has no way to tell which is which. */}
              <p data-numeric className="truncate font-mono text-[0.625rem] text-ink-faint">
                {item.mint.slice(0, 6)}…{item.mint.slice(-4)}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Badge
              label={PRIORITY_LABEL[priority.priority]}
              tone={PRIORITY_TONE[priority.priority]}
              caption="Research priority"
            />
            <Badge
              label={MISSION_LABEL[item.mission]}
              tone={MISSION_TONE[item.mission]}
              caption="Mission status"
            />
          </div>
        </div>

        {/* The one sentence. The most important line on the card. */}
        <p className="text-sm leading-relaxed text-ink">{priority.whyToday}</p>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line/50 pt-2.5">
          {item.grade ? (
            <ConvictionBadge
              grade={item.grade}
              isElite={item.isElite}
              score={item.score}
              showWhy={false}
            />
          ) : null}

          {item.confidence !== null ? (
            <span className="text-xs text-ink-dim">
              <span className="text-ink-faint">Confidence </span>
              <span data-numeric className="font-mono tabular-nums">
                {Math.round(item.confidence)}%
              </span>
            </span>
          ) : null}

          {item.changes.length > 0 ? (
            <span className="text-xs text-ink-dim">
              <span className="text-ink-faint">Changed </span>
              {item.changes.slice(0, 2).map((change) => (
                <span key={change.code} className="ml-1.5 font-mono tabular-nums">
                  {change.label} {change.display}
                </span>
              ))}
            </span>
          ) : null}

          {item.identity && item.identity.clone_risk !== "none" ? (
            <CloneRiskBadge identity={item.identity} showWhy={false} />
          ) : null}

          <Why label="Why here?">
            <div className="flex flex-col gap-1.5">
              <p>
                {PRIORITY_MEANING[priority.priority]} Placed at {priority.score} of 100 by
                the following, each a fact the backend supplied:
              </p>
              <ul className="flex flex-col gap-0.5">
                {priority.drivers.map((driver) => (
                  <li key={driver.reason} className="font-mono text-[0.6875rem]">
                    {driver.points > 0 ? "+" : ""}
                    {driver.points} — {driver.reason}
                  </li>
                ))}
              </ul>
              <p className="text-ink-faint">
                {MISSION_LABEL[item.mission]}: {MISSION_MEANING[item.mission]}{" "}
                <span className="opacity-80">Rule: {MISSION_RULE[item.mission]}</span>
              </p>
              {item.conviction ? (
                <p className="text-ink-faint">
                  The engine&rsquo;s own band is {CONVICTION_LABEL[item.conviction]}; it is an
                  input to this ranking, not a restatement of it.
                </p>
              ) : null}
            </div>
          </Why>
        </div>
      </Panel>
    </li>
  );
}

function Badge({ label, tone, caption }: { label: string; tone: string; caption: string }) {
  return (
    <span className={cn("flex flex-col items-end gap-0.5")} title={caption}>
      <span
        className="rounded-chip border px-2 py-0.5 text-xs font-medium tracking-tight"
        style={{ color: tone, borderColor: `color-mix(in oklch, ${tone} 40%, transparent)` }}
      >
        {label}
      </span>
      <span className="text-[0.5625rem] uppercase tracking-[0.08em] text-ink-faint">
        {caption}
      </span>
    </span>
  );
}
