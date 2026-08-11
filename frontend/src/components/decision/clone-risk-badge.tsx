"use client";

import { Why } from "@/components/decision/why";
import { cn } from "@/lib/utils";
import type { CloneRisk, TokenIdentity } from "@/types/identity";

/**
 * Clone risk — is this token trading on a name it did not establish?
 *
 * Worth its own badge rather than a line in the thesis, because it is the one
 * risk on this platform a user can act on with certainty. Momentum is a
 * judgement; "148 tokens with this name were discovered first" is a fact, and
 * it is the difference between buying a project and buying its impersonator.
 *
 * On the live database 69% of named tokens share a name with something else, so
 * this is the common case rather than an edge one — which is exactly why
 * `none` renders too. Silence would read as "not checked".
 */

const RISK_LABEL: Record<CloneRisk, string> = {
  none: "Unique name",
  low: "Name reused by others",
  moderate: "Possible clone",
  high: "Likely clone",
};

const RISK_TONE: Record<CloneRisk, string> = {
  none: "var(--color-up)",
  low: "var(--color-accent)",
  moderate: "var(--color-warn)",
  high: "var(--color-down)",
};

export function CloneRiskBadge({
  identity,
  showWhy = true,
  className,
}: {
  identity: TokenIdentity | undefined;
  showWhy?: boolean;
  className?: string;
}) {
  if (!identity) return null;

  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <span
        className="text-xs font-medium tracking-tight"
        style={{ color: RISK_TONE[identity.clone_risk] }}
      >
        {RISK_LABEL[identity.clone_risk]}
        {identity.sharing_name > 1 ? (
          <span className="ml-1.5 font-mono tabular-nums text-ink-3" data-numeric>
            {identity.sharing_name}
          </span>
        ) : null}
      </span>
      {showWhy ? (
        <Why>
          {/* Rendered by services/identity.py. Displayed verbatim. */}
          {identity.explanation}
        </Why>
      ) : null}
    </span>
  );
}
