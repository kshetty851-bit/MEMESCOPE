import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AmbientScheduler } from "@/lib/hq/ambient-scheduler";
import { DANCE_LEGS } from "@/lib/hq/dance";

import { pinToBeat, useDanceParty } from "./use-dance-party";

describe("pinToBeat", () => {
  const anim = (animationName: string, startTime: number | null) => ({ animationName, startTime });

  it("puts every dance animation on one clock, and leaves the rest of the office alone", () => {
    const breathing = anim("hq-breathe", 100);
    const figure = anim("hq-dance", 5_000);
    const leftArm = anim("hq-dance-arm-left", 7_000);
    const rightArm = anim("hq-dance-arm-right", null);
    pinToBeat([breathing, figure, leftArm, rightArm], 1_234);

    expect(breathing.startTime).toBe(100);
    expect([figure.startTime, leftArm.startTime, rightArm.startTime]).toEqual([1_234, 1_234, 1_234]);
  });

  it("does not jog a dancer who is already on the beat", () => {
    const onBeat = anim("hq-dance", 1_234 + 15);
    expect(pinToBeat([onBeat], 1_234)).toBe(0);
    expect(onBeat.startTime).toBe(1_249);
  });

  it("re-pins someone who just arrived, and everyone when the track loops", () => {
    const arrived = anim("hq-dance", 60_000);
    expect(pinToBeat([arrived], 1_234)).toBe(1);
    // A loop moves the epoch by the length of the song.
    const looped = anim("hq-dance", 1_234);
    expect(pinToBeat([looped], 1_234 + 170_760)).toBe(1);
  });

  it("puts the whole floor on ONE number when anybody needs pinning", () => {
    // Two dancers each within tolerance of the new epoch, but not of each
    // other — the state that left the live floor running 13ms apart.
    const early = anim("hq-dance", 1_000 - 20);
    const late = anim("hq-dance-arm-left", 1_000 + 20);
    const newcomer = anim("hq-dance-arm-right", 90_000);
    pinToBeat([early, late, newcomer], 1_000);
    expect(new Set([early.startTime, late.startTime, newcomer.startTime])).toEqual(new Set([1_000]));
  });
});

describe("useDanceParty", () => {
  let scheduler: {
    suspendForReport: ReturnType<typeof vi.fn>;
    resumeAfterReport: ReturnType<typeof vi.fn>;
  };
  let release: () => void;
  const setOverride = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    setOverride.mockReset();
    scheduler = {
      suspendForReport: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      ),
      resumeAfterReport: vi.fn(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function mount(initial: { animate?: boolean; musicOn?: boolean; meetingIdle?: boolean }) {
    const ref = { current: scheduler as unknown as AmbientScheduler };
    return renderHook(
      (props: { animate: boolean; musicOn: boolean; meetingIdle: boolean }) =>
        useDanceParty(ref, setOverride, props),
      {
        initialProps: { animate: true, musicOn: false, meetingIdle: true, ...initial },
      },
    );
  }

  /** Every override write, applied in order, as the stage would see it. */
  function painted() {
    let frames: Record<string, { pose: string }> = {};
    for (const [update] of setOverride.mock.calls) {
      frames = typeof update === "function" ? update(frames) : update;
    }
    return frames;
  }

  const longestGather = Math.max(
    ...[...DANCE_LEGS.values()].map((leg) => leg.gather.reduce((t, f) => t + f.hold, 0)),
  );
  const longestDepart = Math.max(
    ...[...DANCE_LEGS.values()].map((leg) => leg.depart.reduce((t, f) => t + f.hold, 0)),
  );

  it("stays put until the music starts", () => {
    const { result } = mount({});
    expect(result.current.phase).toBe("idle");
    expect(scheduler.suspendForReport).not.toHaveBeenCalled();
  });

  it("clears the floor, walks everybody down, and dances", async () => {
    const { result, rerender } = mount({});
    rerender({ animate: true, musicOn: true, meetingIdle: true });
    expect(result.current.phase).toBe("settling");
    expect(scheduler.suspendForReport).toHaveBeenCalledTimes(1);

    await act(async () => release());
    expect(result.current.phase).toBe("gathering");

    await act(async () => {
      vi.advanceTimersByTime(longestGather + 10);
    });
    expect(result.current.phase).toBe("dancing");
    const frames = painted();
    expect(Object.keys(frames).sort()).toEqual([...DANCE_LEGS.keys()].sort());
    for (const [who, frame] of Object.entries(frames)) {
      expect(frame.pose, who).toBe("dancing");
    }
  });

  it("walks everybody home when the music stops, then hands the office back", async () => {
    const { result, rerender } = mount({ musicOn: true });
    await act(async () => release());
    await act(async () => {
      vi.advanceTimersByTime(longestGather + 10);
    });
    expect(result.current.phase).toBe("dancing");

    rerender({ animate: true, musicOn: false, meetingIdle: true });
    expect(result.current.phase).toBe("leaving");

    await act(async () => {
      vi.advanceTimersByTime(longestDepart + 10);
    });
    expect(result.current.phase).toBe("idle");
    expect(setOverride).toHaveBeenLastCalledWith({});
    expect(scheduler.resumeAfterReport).toHaveBeenCalledTimes(1);
  });

  it("never starts over an open report", () => {
    const { result } = mount({ musicOn: true, meetingIdle: false });
    expect(result.current.phase).toBe("idle");
    expect(scheduler.suspendForReport).not.toHaveBeenCalled();
  });

  it("starts once the report closes, if the music is still on", () => {
    const { result, rerender } = mount({ musicOn: true, meetingIdle: false });
    rerender({ animate: true, musicOn: true, meetingIdle: true });
    expect(result.current.phase).toBe("settling");
  });

  it("does not dance at all for someone who asked for stillness", () => {
    const { result } = mount({ musicOn: true, animate: false });
    expect(result.current.phase).toBe("idle");
    expect(result.current.busy).toBe(false);
  });

  it("does not start a walk if the music stopped while the floor was clearing", async () => {
    const { result, rerender } = mount({ musicOn: true });
    expect(result.current.phase).toBe("settling");
    rerender({ animate: true, musicOn: false, meetingIdle: true });
    expect(result.current.phase).toBe("idle");

    // The floor clears late. That old promise must not send anyone walking.
    setOverride.mockClear();
    await act(async () => release());
    await act(async () => {
      vi.advanceTimersByTime(longestGather + 10);
    });
    expect(result.current.phase).toBe("idle");
    expect(setOverride).not.toHaveBeenCalledWith(expect.any(Function));
  });

  it("reports busy the whole time, so the report button can say why it is off", async () => {
    const { result, rerender } = mount({});
    expect(result.current.busy).toBe(false);
    rerender({ animate: true, musicOn: true, meetingIdle: true });
    expect(result.current.busy).toBe(true);
  });
});
