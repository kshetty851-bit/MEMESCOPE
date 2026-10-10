"use client";

import { GenericValue, Section } from "./generic";
import type { Loose } from "./types";

/**
 * Baseline, Monte Carlo and bootstrap blocks. Shared by the backtest and the
 * research views. Their sub-shapes are open in the contract, so they render
 * generically; every sentence inside is the API's.
 */
export function RobustnessSections({
  baseline,
  monteCarlo,
  bootstrap,
}: {
  baseline?: Loose | null;
  monteCarlo?: Loose | null;
  bootstrap?: Loose | null;
}) {
  return (
    <>
      <Section
        title="Baseline comparison"
        hint="The same window against the reference the API compares it with."
        testId="baseline"
      >
        <GenericValue value={baseline ?? {}} name="baseline" />
      </Section>
      <Section
        title="Monte Carlo"
        hint="Percentiles over re-ordered trade sequences, as returned by the API."
        testId="monte-carlo"
      >
        <GenericValue value={monteCarlo ?? {}} name="monte_carlo" />
      </Section>
      <Section title="Bootstrap confidence intervals" testId="bootstrap">
        <GenericValue value={bootstrap ?? {}} name="bootstrap" />
      </Section>
    </>
  );
}
