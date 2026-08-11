import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LaunchOverlay, useLaunchSequence } from "@/components/alpha/launch-sequence";
import { COUNTDOWN_TICK, LAUNCH_TIMELINE, type LaunchPhase } from "@/lib/launch";

/** Drives the hook and records every phase it passes through. */
function Probe({
  active,
  reduced,
  seen,
  onEnter,
}: {
  active: boolean;
  reduced: boolean;
  seen: LaunchPhase[];
  onEnter: () => void;
}) {
  const { phase, count } = useLaunchSequence(active, reduced, onEnter);
  if (seen[seen.length - 1] !== phase) seen.push(phase);
  return <span data-testid="state">{`${phase}:${count ?? "-"}`}</span>;
}

const TOTAL = LAUNCH_TIMELINE.reduce((sum, step) => sum + step.ms, 0);
const APPROVED_MS = LAUNCH_TIMELINE[0]?.ms ?? 0;

/**
 * Advance the clock in slices, each in its own `act`.
 *
 * One long `advanceTimersByTime` inside a single `act` only moves the sequence
 * one step: each step schedules the next timer from an effect, and the effect
 * does not run until React commits at the end of the `act`. Slicing gives the
 * commit a chance to happen between ticks, which is what the real event loop
 * does anyway.
 */
function run(ms: number) {
  for (let elapsed = 0; elapsed < ms; elapsed += 100) {
    act(() => void vi.advanceTimersByTime(100));
  }
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useLaunchSequence", () => {
  it("stays idle until the code is accepted", () => {
    const onEnter = vi.fn();
    render(<Probe active={false} reduced={false} seen={[]} onEnter={onEnter} />);

    run(30_000);

    expect(screen.getByTestId("state")).toHaveTextContent("idle:-");
    expect(onEnter).not.toHaveBeenCalled();
  });

  it("walks the full timeline and enters exactly once", () => {
    const seen: LaunchPhase[] = [];
    const onEnter = vi.fn();
    render(<Probe active reduced={false} seen={seen} onEnter={onEnter} />);

    run(TOTAL + 500);

    expect(seen).toEqual([
      "approved",
      "countdown",
      "ignition",
      "launching",
      "flight",
      "approach",
      "unlock",
      "enter",
    ]);
    expect(onEnter).toHaveBeenCalledTimes(1);
  });

  it("counts 5 down to 1, one digit per tick", () => {
    const onEnter = vi.fn();
    render(<Probe active reduced={false} seen={[]} onEnter={onEnter} />);

    // Past the ACCESS APPROVED beat and into the count.
    run(APPROVED_MS + 100);

    const digits: string[] = [];
    for (let tick = 0; tick < 5; tick += 1) {
      digits.push(screen.getByTestId("state").textContent ?? "");
      run(COUNTDOWN_TICK);
    }

    expect(digits).toEqual([
      "countdown:5",
      "countdown:4",
      "countdown:3",
      "countdown:2",
      "countdown:1",
    ]);
  });

  it("skips the flight entirely under reduced motion", () => {
    const seen: LaunchPhase[] = [];
    const onEnter = vi.fn();
    render(<Probe active reduced seen={seen} onEnter={onEnter} />);

    run(2_000);

    expect(seen).toEqual(["approved", "enter"]);
    expect(onEnter).toHaveBeenCalledTimes(1);
  });

  it("still enters when the motion preference flips mid-sequence", () => {
    // The timeline is frozen when the sequence starts. Were it not, the array
    // would swap under an index pointing into the old one and the visitor —
    // already authenticated — would be stranded on the launch screen.
    const onEnter = vi.fn();
    const { rerender } = render(
      <Probe active reduced={false} seen={[]} onEnter={onEnter} />,
    );

    run(3_000);
    rerender(<Probe active reduced seen={[]} onEnter={onEnter} />);
    run(TOTAL + 500);

    expect(onEnter).toHaveBeenCalled();
  });
});

describe("LaunchOverlay", () => {
  it("announces the milestones and never the digits", () => {
    render(<LaunchOverlay phase="countdown" count={3} />);

    // The digit is on screen for sighted visitors...
    expect(screen.getByText("3")).toBeInTheDocument();
    // ...but a five-step countdown read aloud at 700ms intervals is noise.
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("announces access approval in words", () => {
    render(<LaunchOverlay phase="approved" count={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Access approved. Launching.");
  });

  it("shows nothing at all while the gate is idle", () => {
    const { container } = render(<LaunchOverlay phase="idle" count={null} />);
    expect(container.querySelector(".launch-card")).toBeNull();
  });
});
