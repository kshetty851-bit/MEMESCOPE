import { Label } from "@/components/ui/panel";
import { cn } from "@/lib/utils";
import type { OpportunityExplanation } from "@/types/opportunity";

/**
 * "Why now?" — the five parts of the engine's explanation.
 *
 * Every string here is rendered by the backend from stable reason codes and
 * displayed verbatim. The client composes none of it: a second opinion about
 * the same token, written here, can disagree with the engine that produced it.
 *
 * `limits` is not an appendix. It is where the card says what could *not* be
 * checked, which is the difference between honest coverage and a card that
 * quietly looks complete. It renders even when everything else is absent.
 */
export function WhyNow({
  explanation,
  compact = false,
  className,
}: {
  explanation: OpportunityExplanation;
  /** Trigger and limits only — the card. The drawer shows everything. */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Label>Why now?</Label>
      <p className="text-sm leading-relaxed text-ink-dim">{explanation.trigger}</p>

      {!compact && explanation.boundary && (
        <p className="text-sm leading-relaxed text-ink-faint">{explanation.boundary}</p>
      )}

      {!compact && explanation.delta.length > 0 && (
        <dl className="mt-1 flex flex-col gap-1 rounded-card border border-line/60 bg-surface/40 p-2.5">
          {explanation.delta.map((line) => (
            <dd key={line} data-numeric className="font-mono text-xs text-ink-dim">
              {line}
            </dd>
          ))}
        </dl>
      )}

      {!compact && explanation.corroboration.length > 0 && (
        <ul className="flex flex-col gap-1">
          {explanation.corroboration.map((line) => (
            <li key={line} className="text-xs text-ink-faint">
              {line}
            </li>
          ))}
        </ul>
      )}

      {explanation.limits.length > 0 && (
        <div
          className={cn(
            "mt-1 rounded-card border border-warn/20 bg-warn/[0.03] p-2.5",
            compact && "p-2",
          )}
        >
          <Label className="text-warn/80">Not checked</Label>
          <ul className="mt-1 flex flex-col gap-1">
            {explanation.limits.map((line) => (
              <li key={line} className="text-xs leading-relaxed text-ink-faint">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
