import {
  STAGE_LABEL,
  STAGE_ORDER,
  STAGE_TONE,
  type LifecycleStage,
} from "@/lib/lifecycle";
import { cn } from "@/lib/utils";

/**
 * Lifecycle rail.
 *
 * Four segments showing exactly how far a token has travelled through the
 * division. The current segment carries the stage's hue and a label; completed
 * segments dim; future segments stay hairline. No animation on the fill —
 * a bar that creeps forward implies elapsed progress, and this is a state
 * machine driven by the backend, not a timer.
 */
export function StageRail({
  stage,
  className,
}: {
  stage: LifecycleStage;
  className?: string;
}) {
  const index = STAGE_ORDER.indexOf(stage);
  const tone = STAGE_TONE[stage];

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      role="status"
      aria-label={`Lifecycle stage: ${STAGE_LABEL[stage]}`}
    >
      <div className="flex flex-1 gap-1" aria-hidden>
        {STAGE_ORDER.map((step, position) => {
          const done = position < index;
          const current = position === index;
          return (
            <span
              key={step}
              className="h-[3px] flex-1 rounded-full transition-colors duration-500 ease-[var(--ease-precise)]"
              style={{
                background: current
                  ? tone
                  : done
                    ? `color-mix(in oklch, ${tone} 35%, transparent)`
                    : "var(--color-elevated)",
                boxShadow: current
                  ? `0 0 8px color-mix(in oklch, ${tone} 60%, transparent)`
                  : undefined,
              }}
            />
          );
        })}
      </div>
      <span
        className="shrink-0 text-[0.5625rem] uppercase tracking-[0.1em]"
        style={{ color: tone }}
      >
        {STAGE_LABEL[stage]}
      </span>
    </div>
  );
}
