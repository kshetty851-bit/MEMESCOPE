import { AgentSigil } from "@/components/brand/agent-sigil";
import { Button } from "@/components/ui/button";
import { AGENTS, type AgentId } from "@/lib/design/agents";
import { cn } from "@/lib/utils";

/**
 * Empty and error states.
 *
 * Both are narrated by an agent. "No results" is a dead end; "SCOUT is still
 * sweeping" tells the user the system is working and roughly when to look
 * again. The brand voice rule: never apologise, never blame, always say what
 * happens next.
 */

export function EmptyState({
  agent = "scout",
  title,
  body,
  action,
  className,
}: {
  agent?: AgentId;
  title: string;
  body: string;
  action?: React.ReactNode;
  className?: string;
}) {
  const spec = AGENTS[agent];
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 px-6 py-16 text-center",
        className,
      )}
    >
      <div
        className="ambient flex size-14 items-center justify-center rounded-full border animate-[breathe_6s_ease-in-out_infinite]"
        style={{
          color: spec.hue,
          borderColor: `color-mix(in oklch, ${spec.hue} 30%, transparent)`,
          background: `color-mix(in oklch, ${spec.hue} 8%, transparent)`,
        }}
      >
        <AgentSigil agent={agent} size={26} />
      </div>
      <div className="max-w-sm space-y-1.5">
        <p className="text-md font-medium text-ink">{title}</p>
        <p className="text-sm text-ink-3">{body}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Signal lost",
  body,
  onRetry,
  reference,
  className,
}: {
  title?: string;
  body: string;
  onRetry?: () => void;
  reference?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 px-6 py-16 text-center",
        className,
      )}
      role="alert"
    >
      <div className="flex size-14 items-center justify-center rounded-full border border-sentinel/30 bg-sentinel/10 text-sentinel">
        <AgentSigil agent="sentinel" size={26} />
      </div>
      <div className="max-w-sm space-y-1.5">
        <p className="text-md font-medium text-ink">{title}</p>
        <p className="text-sm text-ink-3">{body}</p>
        {reference && (
          <p data-numeric className="text-xs text-ink-3/70">
            REF {reference}
          </p>
        )}
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Re-establish link
        </Button>
      )}
    </div>
  );
}
