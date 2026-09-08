"use client";

import { Label, Panel } from "@/components/ui/panel";
import { GraduationCyclesPanel } from "@/components/record/graduation-cycles";
import { GraduationPaperPanel } from "@/components/record/graduation-paper";
import { GraduationPanel } from "@/components/record/graduation-panel";
import { Toolbar } from "@/components/ui/toolbar";

/**
 * GRADUATION — what happens after a pump.fun coin completes its curve.
 *
 * Its own page rather than a section of Track Record: that page is the record
 * of what the platform DID, and this is a measurement of what the market does.
 * Mixing them invites reading a market observation as a result the system
 * produced.
 *
 * Three views of one cohort, deliberately in this order: the distribution
 * first, then a fixed-size book over it, then a compounding one. A reader who
 * meets the returns before the distribution has already been told what to
 * think about them.
 */
export default function GraduationPage() {
  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Graduation"
        title="What the hour after graduation actually does."
        description="Every pump.fun coin we see complete its bonding curve is stamped at that moment and re-read on a schedule out to 48 hours. pump.fun publishes no graduation timestamp; this one is ours. Nothing here is traded."
      />

      <Panel density="compact">
        <Label>WHY THIS EXISTS</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          Graduation is widely read as the bullish moment — the coin “made it”.
          Measured across 770 coins over 24 hours, the median was down 99.4%
          from its peak and only 11% were still above the graduation price. This
          page tests the one thing that snapshot could not: whether selling
          quickly changes the answer.
        </p>
      </Panel>

      <GraduationPanel />
      <GraduationPaperPanel />
      <GraduationCyclesPanel />
    </div>
  );
}
