import { Panel } from "@/components/ui/panel";

/**
 * The V4 containment state, said plainly and identically on every wallet
 * surface. The reason string comes from the server so both wallets and HQ
 * print the same words — an operational statement about the platform's
 * evidence, never a market prediction.
 */
export function EntriesPausedBanner({ reason }: { reason: string }) {
  return (
    <Panel density="compact" className="border-warn/30 bg-warn/[0.05]">
      <p className="text-sm font-medium text-ink">
        New entries are paused
        {reason ? (
          <>
            {" — "}
            <span data-numeric className="font-normal">
              {reason}
            </span>
          </>
        ) : null}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-ink-3">
        No validated edge exists on the current admission stream, so this wallet
        is not opening positions. Open positions are still reviewed on every
        pass, exits still settle, and the record keeps being kept. Pausing
        entries is a statement about evidence, not a prediction about the
        market.
      </p>
    </Panel>
  );
}
