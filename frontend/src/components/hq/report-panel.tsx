"use client";

import { EMPLOYEE_BY_ID } from "@/lib/hq/employees";
import { NOT_AVAILABLE, type DialogueLine, type HqReport } from "@/lib/hq/report";

/**
 * LATEST MEMESCOPE HQ REPORT.
 *
 * A rendering of `HqReport` and nothing else. It holds no state, fetches
 * nothing and has no control that could change anything: REFRESH rebuilds the
 * report from the state the page already has, and CLOSE ends the meeting.
 * There is no third button, and there is no code path from this component to
 * a mutation — which is what makes "read only" a property rather than a claim.
 *
 * ── NULL IS PRINTED, NOT HIDDEN ─────────────────────────────────────────
 *
 * A line with no value renders NOT AVAILABLE in the same weight as a real
 * figure, and an unavailable section says so in a sentence rather than
 * disappearing. A report that quietly dropped what it could not measure would
 * read as complete, and the reader would have no way to tell a healthy queue
 * from an unread one.
 */
export function ReportPanel({
  report,
  transcript,
  onRefresh,
  onClose,
  live,
}: {
  report: HqReport;
  transcript: DialogueLine[];
  onRefresh: () => void;
  onClose: () => void;
  /** True while the meeting is still running, so the panel can say so. */
  live: boolean;
}) {
  return (
    <section
      className="hq-report"
      aria-label="Latest MEMESCOPE HQ report"
      /* Polite: the report arrives while a reader may be elsewhere on the
         page, and an assertive region would interrupt them to read a table. */
      aria-live="polite"
    >
      <header className="hq-report-head">
        <div>
          <h2 className="hq-report-title">LATEST MEMESCOPE HQ REPORT</h2>
          <p className="hq-report-stamp">
            <time dateTime={new Date(report.observedAt).toISOString()}>
              {new Date(report.observedAt).toLocaleString()}
            </time>
            {live ? " · meeting in progress" : null}
          </p>
        </div>
        <div className="hq-report-actions">
          <button type="button" className="hq-report-button" onClick={onRefresh}>
            REFRESH REPORT
          </button>
          <button type="button" className="hq-report-button" onClick={onClose}>
            CLOSE REPORT
          </button>
        </div>
      </header>

      <div className="hq-report-block">
        <h3 className="hq-report-heading">EXECUTIVE SUMMARY</h3>
        <ul className="hq-report-summary">
          {report.summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>

      {transcript.length > 0 ? (
        <div className="hq-report-block">
          <h3 className="hq-report-heading">REPORTED IN THE MEETING</h3>
          <ol className="hq-report-transcript">
            {transcript.map((line, index) => (
              <li key={`${line.employee}-${index}`}>
                <span className="hq-report-speaker">
                  {EMPLOYEE_BY_ID.get(line.employee)?.name ?? line.employee}
                </span>
                <span>{line.text}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="hq-report-grid">
        {report.sections.map((section) => (
          <div key={section.id} className="hq-report-block">
            <h3 className="hq-report-heading">{section.title}</h3>
            {section.unavailable ? (
              <p className="hq-report-empty">{section.unavailable}</p>
            ) : section.lines.length === 0 ? (
              <p className="hq-report-empty">NO DATA</p>
            ) : (
              <dl className="hq-report-lines">
                {section.lines.map((line) => (
                  <div key={line.label} className="hq-report-line">
                    <dt>{line.label}</dt>
                    <dd
                      className={
                        line.value === null
                          ? "hq-report-unknown"
                          : line.attention
                            ? "hq-report-attention"
                            : undefined
                      }
                    >
                      {line.value ?? NOT_AVAILABLE}
                    </dd>
                    <p className="hq-report-source">{line.source}</p>
                  </div>
                ))}
              </dl>
            )}
          </div>
        ))}
      </div>

      <div className="hq-report-block">
        <h3 className="hq-report-heading">TOP CURRENT ISSUES</h3>
        {report.issues.length === 0 ? (
          <p className="hq-report-empty">No department is reporting a fault.</p>
        ) : (
          <ul className="hq-report-summary">
            {report.issues.map((issue) => (
              <li key={issue.label}>
                <strong>{issue.label}</strong> — {issue.value ?? NOT_AVAILABLE}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="hq-report-block">
        <h3 className="hq-report-heading">ACTION ITEMS</h3>
        {report.actions.length === 0 ? (
          /* Nothing to do is a real answer. An empty list with an invented
             "monitor the queues" would be advice HQ has no standing to give. */
          <p className="hq-report-empty">None. No department is reporting a fault.</p>
        ) : (
          <ul className="hq-report-summary">
            {report.actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
