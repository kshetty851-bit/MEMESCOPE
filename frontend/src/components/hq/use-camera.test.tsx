import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCamera } from "@/components/hq/use-camera";
import { AUTO_HOLD_MS } from "@/lib/hq/camera";
import { UNKNOWN_HQ_STATE, type HqState } from "@/lib/hq/adapter";
import type { EmployeeId } from "@/lib/hq/employees";

/**
 * WHO DECIDES WHERE THE CAMERA LOOKS.
 *
 * Three rules, in order, and the tests exist because all three are the kind
 * that decay silently: a camera that quietly starts overriding the reader, or
 * quietly starts following ambient noise, still looks fine in a screenshot.
 */

function reacting(who: EmployeeId | null, speech = "Target hit."): HqState {
  if (!who) return UNKNOWN_HQ_STATE;
  return {
    ...UNKNOWN_HQ_STATE,
    employees: {
      ...UNKNOWN_HQ_STATE.employees,
      [who]: { ...UNKNOWN_HQ_STATE.employees[who], speech },
    },
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("the reader always wins", () => {
  it("holds a manual selection with no timeout", () => {
    const { result, rerender } = renderHook(
      ({ state }: { state: HqState }) => useCamera(state, true),
      { initialProps: { state: UNKNOWN_HQ_STATE } },
    );

    act(() => result.current.select("byte"));
    expect(result.current.target).toEqual({ kind: "desk", employee: "byte" });

    // Long past the auto hold, and with somebody else mid-reaction.
    rerender({ state: reacting("karthik") });
    act(() => void vi.advanceTimersByTime(AUTO_HOLD_MS * 4));
    expect(result.current.target).toEqual({ kind: "desk", employee: "byte" });
    expect(result.current.auto).toBe(false);
  });

  it("returns to the room when the reader clears the selection", () => {
    const { result } = renderHook(() => useCamera(UNKNOWN_HQ_STATE, true));
    act(() => result.current.select("nova"));
    act(() => result.current.select(null));
    expect(result.current.target.kind).toBe("room");
    expect(result.current.selected).toBeNull();
  });
});

describe("following a real reaction", () => {
  it("visits, holds, and comes back on its own", () => {
    const { result, rerender } = renderHook(
      ({ state }: { state: HqState }) => useCamera(state, true),
      { initialProps: { state: UNKNOWN_HQ_STATE } },
    );
    expect(result.current.target.kind).toBe("room");

    rerender({ state: reacting("karthik") });
    expect(result.current.target).toEqual({ kind: "desk", employee: "karthik" });
    expect(result.current.auto).toBe(true);
    // An automatic visit is not a selection: the dossier must not open by itself.
    expect(result.current.selected).toBeNull();

    act(() => void vi.advanceTimersByTime(AUTO_HOLD_MS + 50));
    expect(result.current.target.kind).toBe("room");
  });

  it("does not restart the hold while the same reaction persists", () => {
    // A transient lives across many renders. Re-triggering on each one would
    // reset the timer for ever and pin the camera there.
    const state = reacting("patch");
    const { result, rerender } = renderHook(
      ({ s }: { s: HqState }) => useCamera(s, true),
      { initialProps: { s: UNKNOWN_HQ_STATE } },
    );
    rerender({ s: state });
    act(() => void vi.advanceTimersByTime(AUTO_HOLD_MS / 2));
    rerender({ s: { ...state } });
    rerender({ s: { ...state } });
    act(() => void vi.advanceTimersByTime(AUTO_HOLD_MS / 2 + 100));
    expect(result.current.target.kind).toBe("room");
  });

  it("never follows when following is off", () => {
    // Reduced motion. Clicking still frames; the camera never moves by itself.
    const { result, rerender } = renderHook(
      ({ s }: { s: HqState }) => useCamera(s, false),
      { initialProps: { s: UNKNOWN_HQ_STATE } },
    );
    rerender({ s: reacting("karthik") });
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current.target.kind).toBe("room");

    act(() => result.current.select("karthik"));
    expect(result.current.target).toEqual({ kind: "desk", employee: "karthik" });
  });
});

describe("what it refuses to follow", () => {
  /**
   * The rule that keeps a close-up meaningful.
   *
   * Ambient routines fire on a timer and carry their own `speech` on the
   * *frame*. The adapter's `speech` on a *reading* is set only by `react()`,
   * which fires on a witnessed change in a published figure. This hook reads
   * the reading, never the frame — so the camera cannot be pulled by somebody
   * walking to the coffee machine.
   *
   * If it could, a close-up would mean something roughly a third of the time,
   * and the one occasion it mattered would be indistinguishable from the noise.
   */
  it("cannot be moved by anything that is not a published reading", () => {
    // Structural, and asserted through the interface rather than the source:
    // the hook takes `HqState` and nothing else, so the ambient frames — which
    // carry their own chatter `speech` and fire on a timer — are not reachable
    // from here at all. A state with no reading-level speech therefore leaves
    // the camera on the room no matter what the room is animating.
    const chatty: HqState = {
      ...UNKNOWN_HQ_STATE,
      // Every employee busy with ambient personality, none of it witnessed.
      operational: ["byte", "echo", "karthik"] as EmployeeId[],
      activity: "BUSY",
    };
    const { result, rerender } = renderHook(
      ({ s }: { s: HqState }) => useCamera(s, true),
      { initialProps: { s: UNKNOWN_HQ_STATE } },
    );
    rerender({ s: chatty });
    act(() => void vi.advanceTimersByTime(5_000));
    expect(result.current.target.kind).toBe("room");
  });

  it("stays on the room when nobody is reacting", () => {
    const { result } = renderHook(() => useCamera(UNKNOWN_HQ_STATE, true));
    act(() => void vi.advanceTimersByTime(30_000));
    expect(result.current.target.kind).toBe("room");
    expect(result.current.auto).toBe(false);
  });
});
