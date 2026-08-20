"use client";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { Panel } from "@/components/ui/panel";
import type { CaseStage, CaseStageStatus, TokenCaseFile , CaseEvidenceGroup } from "@/lib/hq/case-file";

/**
 * THE TOKEN CASE FILE PANEL.
 *
 * An analyst dossier for one mint: what MEMESCOPE actually did with it, stage
 * by stage, and why. Every row on this panel traces to one field in
 * `TokenCaseFile` — nothing here composes a sentence from data the adapter
 * did not already decide, which is what keeps this component from becoming a
 * second place that could get a stage's truthfulness wrong.
 */

const STAGE_ROWS: Array<{
  key: keyof TokenCaseFile["stages"];
  employee: string;
  label: string;
}> = [
  { key: "discovery", employee: "Radar", label: "Discovery" },
  { key: "scoring", employee: "Luna", label: "Scoring" },
  { key: "market", employee: "Dex", label: "Market / Liquidity" },
  { key: "safety", employee: "Atlas", label: "Safety" },
  { key: "decision", employee: "—", label: "Candidate Decision" },
  { key: "execution", employee: "Rex", label: "Paper Execution" },
];

const STATUS_TEXT: Record<CaseStageStatus, string> = {
  PASSED: "Passed",
  FAILED: "Failed",
  PENDING: "Pending",
  // Evaluated, and still not establishable. Distinct from "Not available",
  // which means nothing answered at all.
  UNKNOWN: "Unknown",
  UNAVAILABLE: "Not available",
};

function StatusChip({ status, stale }: { status: CaseStageStatus; stale: boolean }) {
  return (
    <span
      className="hq-case-chip"
      data-status={status}
      data-stale={stale ? "true" : "false"}
    >
      {STATUS_TEXT[status]}
      {stale ? " · stale" : ""}
    </span>
  );
}

function StageRow({
  employee,
  label,
  stage,
}: {
  employee: string;
  label: string;
  stage: CaseStage;
}) {
  return (
    <div className="hq-case-row" data-testid={`hq-case-stage-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-semibold text-[var(--color-ink)]">{employee}</span>
          <span className="text-[11px] text-[var(--color-ink-3,var(--color-ink))]">{label}</span>
        </div>
        <StatusChip status={stage.status} stale={stage.stale} />
      </div>
      <p className="mt-0.5 text-xs text-[var(--color-ink)]">{stage.summary}</p>
      {stage.reasonCodes.length > 0 ? (
        <p className="mt-0.5 text-[11px] text-[var(--color-ink-3,var(--color-ink))]">
          {stage.reasonCodes.join(", ")}
        </p>
      ) : null}
      {stage.timestamp ? (
        <p className="mt-0.5 text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
          {stage.timestamp}
        </p>
      ) : null}
    </div>
  );
}

function shortMint(mint: string): string {
  return mint.length > 10 ? `${mint.slice(0, 4)}…${mint.slice(-4)}` : mint;
}

export interface CaseFilePanelProps {
  file: TokenCaseFile;
  onClose: () => void;
}

/** The evidence sections, in the order a reader works through a case. */
const EVIDENCE_GROUPS: Array<{
  key: CaseEvidenceGroup;
  title: string;
  note: string;
}> = [
  { key: "scoring", title: "Scoring", note: "Luna" },
  { key: "market", title: "Market", note: "Dex — depth and price only, never a safety claim" },
  { key: "security", title: "Security", note: "Atlas — on-chain evidence" },
  { key: "paper", title: "Paper position", note: "Rex" },
];

export function CaseFilePanel({ file, onClose }: CaseFilePanelProps) {
  const currentMcap = file.evidence.find((row) => row.label === "Current MCAP")?.value;

  return (
    <Panel>
      <div className="flex flex-col gap-3 p-4" data-testid="hq-case-file">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <TokenAvatar mint={file.mint} imageUrl={file.imageUrl} size={40} />
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                {file.name ?? file.symbol ?? "Unnamed token"}
                {file.symbol ? (
                  <span className="ml-1.5 text-xs font-normal text-[var(--color-ink-3,var(--color-ink))]">
                    {file.symbol}
                  </span>
                ) : null}
              </h2>
              <button
                type="button"
                className="text-[11px] text-[var(--color-ink-3,var(--color-ink))] underline decoration-dotted"
                onClick={() => navigator.clipboard?.writeText(file.mint)}
                title="Copy mint address"
              >
                {shortMint(file.mint)}
              </button>
              <p className="text-[11px] text-[var(--color-ink-3,var(--color-ink))]">
                {currentMcap ? `MCAP ${currentMcap} · ` : ""}
                Stage: {file.currentStage} · {file.overallState}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[var(--color-line)] px-2 py-1 text-xs text-[var(--color-ink)]"
          >
            Close
          </button>
        </div>

        <p className="text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
          {file.lastUpdatedAt ? `Last updated ${file.lastUpdatedAt}` : "No evidence has been read yet."}
        </p>

        <div className="flex flex-col gap-2 border-t border-[var(--color-line)] pt-2">
          {STAGE_ROWS.map((row) => (
            <StageRow key={row.key} employee={row.employee} label={row.label} stage={file.stages[row.key]} />
          ))}
        </div>

        <div className="border-t border-[var(--color-line)] pt-2" data-testid="hq-case-evidence">
          {/*
            Grouped by department, not flattened into one list.

            "Liquidity $24,300" and "Liquidity security: Unknown" are adjacent
            strings about entirely different things, and a single table invites
            a reader to treat the first as evidence for the second. Dex
            reporting depth is not Atlas clearing it. The headings are the
            cheapest possible way to keep those apart.
          */}
          {EVIDENCE_GROUPS.map(({ key, title, note }) => {
            const rows = file.evidence.filter((row) => row.group === key);
            if (rows.length === 0) return null;
            return (
              <section key={key} className="mb-2 last:mb-0">
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
                  {title}
                  <span className="ml-2 font-normal normal-case tracking-normal opacity-70">
                    {note}
                  </span>
                </h3>
                <table className="w-full text-left text-xs" data-testid={`hq-case-evidence-${key}`}>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.label} className="border-t border-[var(--color-line)]">
                        <th
                          scope="row"
                          className="py-1 pr-3 font-normal text-[var(--color-ink-3,var(--color-ink))]"
                        >
                          {row.label}
                          {row.when ? (
                            <span className="ml-1 text-[9px] uppercase opacity-70">
                              {row.when === "entry"
                                ? "at entry"
                                : row.when === "current"
                                  ? "current"
                                  : "last checked"}
                            </span>
                          ) : null}
                        </th>
                        <td className="py-1 pr-3 text-[var(--color-ink)]">
                          {row.value ?? (
                            <span className="text-[var(--color-ink-3,var(--color-ink))]">
                              NOT AVAILABLE
                            </span>
                          )}
                        </td>
                        <td className="py-1 text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
                          {row.source}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}
