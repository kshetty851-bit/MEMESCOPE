import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

import { Unavailable, formatUtc, humanize } from "./display";
import type { ResearchRequirement, ResearchState, ResearchStatus } from "./types";

/**
 * RESEARCH STATUS — where the lab is on the road to an authoritative verdict.
 *
 * Two rules this panel exists to keep:
 *
 *  1. The verdict is UNCERTAIN until the API says AUTHORITATIVE_RESULT *and*
 *     the verdict engine exists. The client does not trust the `verdict` string
 *     in any other state: a stray value from the server in a non-final state
 *     still renders as UNCERTAIN, so an "edge" can never be shown early.
 *  2. A requirement that could not be measured is shown unmet with its reason;
 *     the client never decides one is "close enough".
 */

const STATE_CHIP: Record<
  ResearchState,
  { tone: "neutral" | "plasma" | "warn" | "safe" | "apex"; hint: string }
> = {
  NOT_STARTED: { tone: "neutral", hint: "forward collection has not begun" },
  COLLECTING: { tone: "plasma", hint: "forward collection is running" },
  INSUFFICIENT_DATA: { tone: "warn", hint: "at least one requirement is unmet" },
  READY_FOR_ANALYSIS: { tone: "safe", hint: "every requirement is met" },
  ANALYZING: { tone: "plasma", hint: "an authoritative analysis is in progress" },
  AUTHORITATIVE_RESULT: { tone: "apex", hint: "a completed analysis over the pre-registered splits" },
};

/** The only verdict text the panel will print, and when. */
export function displayVerdict(status: ResearchStatus): string {
  const final = status.state === "AUTHORITATIVE_RESULT" && status.verdict_engine_available;
  if (!final) return "UNCERTAIN";
  return status.verdict.replace(/_/g, " ").toUpperCase();
}

function RequirementsTable({ requirements }: { requirements: ResearchRequirement[] }) {
  if (requirements.length === 0) {
    return <p className="text-sm text-ink-3">No requirements reported.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <caption className="sr-only">Minimum evidence requirements</caption>
        <thead>
          <tr className="border-y border-line bg-sunken text-left text-label uppercase text-ink-3">
            <th scope="col" className="px-3 py-2 font-medium">Requirement</th>
            <th scope="col" className="px-3 py-2 font-medium">Threshold</th>
            <th scope="col" className="px-3 py-2 font-medium">Observed</th>
            <th scope="col" className="px-3 py-2 font-medium">Met</th>
            <th scope="col" className="px-3 py-2 font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {requirements.map((r) => (
            <tr
              key={r.key}
              data-testid={`requirement-${r.key}`}
              data-met={r.met ? "true" : "false"}
              className="border-b border-line-subtle align-top"
            >
              <th scope="row" className="px-3 py-2 text-left font-medium text-ink">
                {r.label}
              </th>
              <td className="px-3 py-2 text-ink-2" data-numeric>{r.threshold}</td>
              <td className="px-3 py-2 text-ink-2" data-numeric>
                {r.observed === null ? <Unavailable reason={r.reason ?? "not_measured"} /> : r.observed}
              </td>
              <td className="px-3 py-2">
                <span className={cn("font-semibold", r.met ? "text-up" : "text-down")}>
                  <span aria-hidden>{r.met ? "✓" : "✗"}</span>{" "}
                  {r.met ? "met" : "not met"}
                </span>
              </td>
              <td className="px-3 py-2 text-xs text-ink-3">
                {r.reason ? humanize(r.reason) : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ResearchStatusPanel({ status }: { status: ResearchStatus }) {
  const chip = STATE_CHIP[status.state] ?? { tone: "neutral" as const, hint: "" };
  const verdict = displayVerdict(status);
  const met = status.requirements.filter((r) => r.met).length;

  return (
    <Panel data-testid="research-status">
      <PanelHeader>
        <div className="flex flex-col gap-1">
          <PanelTitle>Research status</PanelTitle>
          <p className="text-xs text-ink-3">
            {status.experiment_key ? `Experiment ${status.experiment_key}` : "No experiment registered"}
            {status.forward_start ? ` · forward since ${formatUtc(status.forward_start)}` : ""}
          </p>
        </div>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-3">
        <Badge
          tone={chip.tone}
          className="px-3 py-1.5 text-md font-semibold uppercase tracking-wider"
        >
          <span data-testid="research-state">{humanize(status.state)}</span>
        </Badge>
        <span
          data-testid="research-verdict"
          className={cn(
            "rounded-md border px-3 py-1.5 text-md font-semibold tracking-wider",
            verdict === "UNCERTAIN"
              ? "border-warn/40 bg-warn/10 text-warn"
              : "border-line-strong bg-raised text-ink",
          )}
        >
          VERDICT: {verdict}
        </span>
        <span className="text-xs text-ink-3">{chip.hint}</span>
      </div>

      <p className="mt-4 max-w-[70ch] text-sm text-ink-2">{status.explanation}</p>

      {status.verdict_engine_available ? null : (
        <p className="mt-2 text-xs text-ink-3">
          The verdict engine is not available yet, so the verdict is UNCERTAIN by construction.
        </p>
      )}

      <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="text-label uppercase text-ink-3">Forward days</dt>
          <dd data-numeric data-testid="research-forward-days">
            {status.forward_days === null ? (
              <Unavailable reason="forward_not_started" />
            ) : (
              status.forward_days.toFixed(1)
            )}
          </dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Requirements met</dt>
          <dd data-numeric>
            {met} of {status.requirements.length}
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <RequirementsTable requirements={status.requirements} />
      </div>
    </Panel>
  );
}
