/**
 * Alpha feedback transport.
 *
 * The submission path is isolated here so the destination can change without
 * touching the form. Right now there is no feedback endpoint on the backend and
 * building one is not an alpha blocker — what matters is that 10–25 invited
 * testers can report something the moment they see it, and that nothing they
 * type is ever lost.
 *
 * So `submitFeedback` degrades in a defined order:
 *
 *   1. `NEXT_PUBLIC_FEEDBACK_ENDPOINT` — POST the report as JSON.
 *   2. `NEXT_PUBLIC_FEEDBACK_URL` — open the configured form or issue tracker.
 *   3. Neither — return the report so the UI can show it for copying.
 *
 * Every branch returns the same shape, so the form does not know or care which
 * one ran. Swapping in a real endpoint later is a configuration change, and
 * connecting a third-party service is one function.
 *
 * The report always carries the build SHA and the page it came from. Alpha
 * reports arrive hours later as "the scores looked wrong"; without those two
 * fields there is no way to reconstruct what the user was looking at.
 */

import { BUILD, env } from "@/lib/env";

export const FEEDBACK_KINDS = ["bug", "suggestion", "feature", "general"] as const;

export type FeedbackKind = (typeof FEEDBACK_KINDS)[number];

export const FEEDBACK_LABEL: Record<FeedbackKind, string> = {
  bug: "Bug",
  suggestion: "Suggestion",
  feature: "Feature request",
  general: "General feedback",
};

export interface FeedbackReport {
  kind: FeedbackKind;
  message: string;
  /** Where the user was when they opened the form. */
  path: string;
  /** Which build produced what they saw. */
  build: string;
  environment: string;
  userAgent: string;
  submittedAt: string;
}

export type FeedbackOutcome =
  /** Delivered to a real endpoint. */
  | { status: "sent" }
  /** Handed off to an external form; the user finishes there. */
  | { status: "redirected"; url: string }
  /** Nowhere to send it — the UI shows the text so it can be copied. */
  | { status: "unconfigured"; report: FeedbackReport }
  | { status: "failed"; report: FeedbackReport; error: string };

export function buildReport(kind: FeedbackKind, message: string): FeedbackReport {
  return {
    kind,
    message: message.trim(),
    path: typeof window === "undefined" ? "" : window.location.pathname,
    build: BUILD.sha,
    environment: BUILD.environment,
    userAgent: typeof navigator === "undefined" ? "" : navigator.userAgent,
    submittedAt: new Date().toISOString(),
  };
}

export async function submitFeedback(report: FeedbackReport): Promise<FeedbackOutcome> {
  const endpoint = env.NEXT_PUBLIC_FEEDBACK_ENDPOINT;

  if (endpoint !== "") {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(report),
      });
      if (!response.ok) {
        return {
          status: "failed",
          report,
          error: `The feedback service responded ${response.status}.`,
        };
      }
      return { status: "sent" };
    } catch {
      // The report is handed back rather than discarded: a tester who has just
      // written three paragraphs about a bug should never lose them to a
      // network error.
      return {
        status: "failed",
        report,
        error: "Could not reach the feedback service.",
      };
    }
  }

  if (BUILD.feedbackUrl !== "") {
    return { status: "redirected", url: BUILD.feedbackUrl };
  }

  return { status: "unconfigured", report };
}

/** The report as text, for copying into an email or an issue. */
export function formatReport(report: FeedbackReport): string {
  return [
    `[${FEEDBACK_LABEL[report.kind]}] MEMESCOPE alpha`,
    "",
    report.message,
    "",
    `Page:  ${report.path}`,
    `Build: ${report.build} (${report.environment})`,
    `When:  ${report.submittedAt}`,
    `Agent: ${report.userAgent}`,
  ].join("\n");
}
