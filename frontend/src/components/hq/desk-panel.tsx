"use client";

import { useQuery } from "@tanstack/react-query";

import { Panel } from "@/components/ui/panel";
import { Portrait } from "@/components/hq/portrait";
import { EMPLOYEE_BY_ID, type EmployeeId } from "@/lib/hq/employees";
import { fetchDeskDossier, type DeskEvent } from "@/lib/hq/dossier";

/**
 * WHAT THIS DESK DID TODAY.
 *
 * ── AN UNMEASURED DESK IS THE COMMON CASE, NOT THE ERROR CASE ───────────
 *
 * Ten of the fourteen have no event stream — they report a gauge, and a gauge
 * has no history. This renders the backend's own sentence explaining that,
 * with the same weight as a timeline would get, because "there is nothing to
 * replay here" is a real answer to "what did they do today" and a reader who
 * is told it stops wondering.
 *
 * What it must never do is show an empty timeline for those desks. An empty
 * list and a quiet day look identical, and only one of them is true.
 */

const KIND_COLOR: Record<DeskEvent["kind"], string> = {
  action: "var(--color-accent)",
  incident: "var(--color-warn)",
  trade: "var(--color-up)",
  admission: "var(--color-ink-3, var(--color-ink))",
};

function clock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function DeskPanel({
  employee,
  onClose,
}: {
  employee: EmployeeId;
  onClose: () => void;
}) {
  const who = EMPLOYEE_BY_ID.get(employee);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["hq", "desk", employee],
    queryFn: () => fetchDeskDossier(employee),
    // A day's log does not change fast, and the panel is opened by a click.
    staleTime: 60_000,
  });

  return (
    <Panel>
      <section className="flex flex-col gap-3 p-4" aria-label={`${who?.name ?? employee}: last 24 hours`}>
        <header className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <Portrait id={employee} size={44} />
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                {who?.name ?? employee} · last 24 hours
              </h2>
              <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                {who?.role}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs text-[var(--color-ink)]"
          >
            Close
          </button>
        </header>

        {isLoading ? (
          <p className="py-3 text-xs text-[var(--color-ink-3,var(--color-ink))]">Reading the log…</p>
        ) : isError || !data ? (
          <p className="py-3 text-xs text-[var(--color-ink-3,var(--color-ink))]">
            The log could not be read. Nothing is shown rather than a partial day.
          </p>
        ) : !data.measured ? (
          /* The common case. The backend's sentence, verbatim. */
          <div data-testid="desk-unlogged">
            <p className="font-mono text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
              No log for this desk
            </p>
            <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink-3,var(--color-ink))]">
              {data.detail}
            </p>
          </div>
        ) : (
          <>
            <p className="text-xs text-[var(--color-ink)]" data-testid="desk-headline">
              {data.headline}
            </p>
            <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
              {data.detail}
            </p>

            {data.counts.length > 0 ? (
              <table className="w-full text-left text-xs" data-testid="desk-counts">
                <tbody>
                  {data.counts.map((count) => (
                    <tr key={count.label} className="border-t border-[var(--color-line)]">
                      <th
                        scope="row"
                        className="py-1 pr-3 font-normal text-[var(--color-ink-3,var(--color-ink))]"
                        style={count.label.startsWith(" ") ? { paddingLeft: 12 } : undefined}
                      >
                        {count.label.trim()}
                      </th>
                      <td className="py-1 pr-3 font-mono text-[var(--color-ink)]">{count.value}</td>
                      {/* Every figure names its field, like every other metric
                          in this room. */}
                      <td className="py-1 text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
                        {count.source}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}

            {(data.findings?.length ?? 0) > 0 ? (
              <div className="mt-1 flex flex-col gap-2" data-testid="desk-findings">
                <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
                  What this desk can say
                </p>
                {data.findings!.map((finding) => (
                  <article
                    key={finding.headline}
                    className="border-l-2 border-[var(--color-line)] pl-2"
                  >
                    <h3 className="text-xs font-semibold text-[var(--color-ink)]">
                      {finding.headline}
                    </h3>
                    <p className="mt-0.5 text-[11px] leading-snug text-[var(--color-ink)]">
                      {finding.evidence}
                    </p>
                    {/* The lever, visually subordinate to the evidence above
                        it — deliberately. The measurement is the finding; what
                        would have to move is a consequence of it, and styling
                        the two equally would invite a reader to act on the
                        second without checking the first. */}
                    {finding.lever ? (
                      <p className="mt-1 text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
                        {finding.lever}
                      </p>
                    ) : null}
                    <p className="mt-0.5 font-mono text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
                      {finding.source}
                    </p>
                  </article>
                ))}
              </div>
            ) : null}

            {(data.readings?.length ?? 0) > 0 ? (
              <table className="w-full text-left text-xs" data-testid="desk-readings">
                <tbody>
                  {data.readings!.map((reading) => (
                    <tr key={reading.label} className="border-t border-[var(--color-line)]">
                      <th
                        scope="row"
                        className="py-1 pr-3 font-normal text-[var(--color-ink-3,var(--color-ink))]"
                      >
                        {reading.label}
                      </th>
                      <td className="py-1 pr-3 font-mono text-[var(--color-ink)]">
                        {reading.value}
                      </td>
                      <td className="py-1 text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
                        {reading.source}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}

            {(data.suggestions?.length ?? 0) > 0 ? (
              <div
                className="mt-1 flex flex-col gap-2 rounded-md border border-[var(--color-line)] p-3"
                data-testid="desk-suggestions"
              >
                {/* Its own box, below the findings and visibly separated from
                    them. A finding is what the record says; a suggestion is
                    what somebody might do about it. Running the two together
                    is how a measurement quietly becomes advice. */}
                <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
                  Suggestion box
                </p>
                {data.suggestions!.map((suggestion) => (
                  <article key={suggestion.title} className="flex flex-col gap-0.5">
                    <h3 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-ink)]">
                      {/* The verdict marker. An unsupported suggestion is not
                          hidden — it is the most useful thing on the board,
                          because "take profit earlier" is the first idea
                          anybody has and the replay already answered it. */}
                      <span
                        aria-hidden="true"
                        className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{
                          background: suggestion.supported
                            ? "var(--color-up)"
                            : "var(--color-ink-3, var(--color-ink))",
                        }}
                      />
                      {suggestion.title}
                      <span className="sr-only">
                        {suggestion.supported
                          ? " — supported by the record"
                          : " — the record argues against this"}
                      </span>
                    </h3>
                    <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
                      {suggestion.detail}
                    </p>
                    <p className="font-mono text-[11px] text-[var(--color-ink)]">
                      {suggestion.outcome}
                    </p>
                    <p className="font-mono text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
                      {suggestion.source}
                    </p>
                  </article>
                ))}
              </div>
            ) : null}

            {data.timeline.length > 0 ? (
              <div className="mt-1">
                <p className="pb-1 text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
                  Most recent{data.timeline.length >= 40 ? " (capped)" : ""}
                </p>
                <ol className="flex flex-col" data-testid="desk-timeline">
                  {data.timeline.map((event, i) => (
                    <li
                      key={`${event.at}-${i}`}
                      className="flex gap-2 border-t border-[var(--color-line)] py-1 text-[11px]"
                    >
                      <time className="shrink-0 font-mono text-[var(--color-ink-3,var(--color-ink))]">
                        {clock(event.at)}
                      </time>
                      <span
                        className="shrink-0 font-mono text-[10px] uppercase"
                        style={{ color: KIND_COLOR[event.kind] }}
                      >
                        {event.kind}
                      </span>
                      <span className="min-w-0">
                        <span className="truncate font-mono text-[var(--color-ink)]">
                          {event.label}
                        </span>
                        <span className="block text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
                          {event.detail}
                        </span>
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <p className="py-2 text-xs text-[var(--color-ink-3,var(--color-ink))]">
                Nothing in the window. This desk keeps a log and it is empty —
                which is a reading, not a gap.
              </p>
            )}

            <p className="text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-70">
              Sources: <span className="font-mono">{data.sources.join(", ")}</span>
            </p>
          </>
        )}
      </section>
    </Panel>
  );
}
