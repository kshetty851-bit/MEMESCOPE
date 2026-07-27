import { AiCore } from "@/components/brand/ai-core";

/**
 * Route-level loading. The Core is the loading state — the instrument is
 * spinning up, which is more honest and more on-brand than a spinner.
 */
export default function Loading() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6">
      <AiCore size={220} label="Loading intelligence" />
      <p className="text-label uppercase text-ink-faint">Synchronising intelligence</p>
    </div>
  );
}
