import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UNKNOWN_HQ_STATE } from "@/lib/hq/adapter";
import type { AmbientScheduler } from "@/lib/hq/ambient-scheduler";
import { REPORT_ORDER } from "@/lib/hq/report-meeting";
import { useReportMeeting } from "@/components/hq/use-report-meeting";

/**
 * The meeting, driven by a fake clock.
 *
 * The browser could not verify this reliably — its pane reports a 0×0 viewport,
 * which puts the page on its mobile path and skips the choreography entirely.
 * Fake timers make the whole sequence deterministic and, unlike a screenshot,
 * they keep checking it.
 */

function fakeScheduler() {
  const calls = { suspend: 0, resume: 0 };
  const scheduler = {
    suspendForReport: () => {
      calls.suspend += 1;
      return Promise.resolve();
    },
    resumeAfterReport: () => {
      calls.resume += 1;
    },
  } as unknown as AmbientScheduler;
  return { scheduler, calls, ref: { current: scheduler } };
}

function setup(animate = true) {
  const fake = fakeScheduler();
  const frames: Array<Record<string, unknown>> = [];
  const setOverride = vi.fn((next) => {
    frames.push(typeof next === "function" ? next({}) : next);
  });
  const view = renderHook(() =>
    useReportMeeting(UNKNOWN_HQ_STATE, fake.ref, setOverride, { animate }),
  );
  return { view, fake, setOverride, frames };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("starting a meeting", () => {
  it("is idle until asked", () => {
    const { view } = setup();
    expect(view.result.current.phase).toBe("idle");
    expect(view.result.current.busy).toBe(false);
    expect(view.result.current.report).toBeNull();
  });

  it("clears the floor before anyone walks anywhere", async () => {
    const { view, fake } = setup();
    await act(async () => {
      view.result.current.start();
    });
    // The scheduler is asked to stand down, and only then does anyone move.
    expect(fake.calls.suspend).toBe(1);
    expect(["gathering", "settling"]).toContain(view.result.current.phase);
  });

  it("refuses a second meeting while one is running", async () => {
    const { view, fake } = setup();
    await act(async () => {
      view.result.current.start();
      view.result.current.start();
      view.result.current.start();
    });
    expect(fake.calls.suspend).toBe(1);
    expect(view.result.current.busy).toBe(true);
  });

  it("builds the report at the moment it is asked, not continuously", async () => {
    const { view } = setup();
    await act(async () => {
      view.result.current.start();
    });
    const first = view.result.current.report;
    expect(first).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(4_000);
    });
    // Same object identity: the report does not re-derive itself under a
    // reader, which is what makes a figure in it quotable.
    expect(view.result.current.report).toBe(first);
  });
});

describe("the meeting runs and then holds", () => {
  it("reaches the meeting, speaks every turn, then holds for the reader", async () => {
    const { view } = setup();
    await act(async () => {
      view.result.current.start();
    });
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(view.result.current.phase).toBe("meeting");
    expect(view.result.current.speaking).not.toBeNull();

    // Stepped rather than advanced in one jump: each turn's timer is created
    // by the effect that runs *after* the previous turn re-rendered, so a
    // single large advance only ever plays one of them.
    for (let step = 0; step < 20; step += 1) {
      await act(async () => {
        vi.advanceTimersByTime(4_000);
      });
    }
    // It stops at `holding` and stays there: the panel is open and nobody
    // wanders off while it is being read.
    expect(view.result.current.phase).toBe("holding");
    expect(view.result.current.said).toHaveLength(REPORT_ORDER.length + 1);
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(view.result.current.phase).toBe("holding");
  });

  it("shows the panel from the first spoken line", async () => {
    const { view } = setup();
    await act(async () => {
      view.result.current.start();
    });
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(view.result.current.panelOpen).toBe(true);
  });
});

describe("closing", () => {
  it("walks everyone back and hands the floor to ambient", async () => {
    const { view, fake, setOverride } = setup();
    await act(async () => {
      view.result.current.start();
    });
    for (let step = 0; step < 25; step += 1) {
      await act(async () => {
        vi.advanceTimersByTime(4_000);
      });
    }
    await act(async () => {
      view.result.current.close();
    });
    expect(view.result.current.phase).toBe("leaving");
    expect(fake.calls.resume).toBe(0);

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(view.result.current.phase).toBe("idle");
    expect(view.result.current.report).toBeNull();
    expect(fake.calls.resume).toBe(1);
    // The last write empties the override, so ambient owns every actor again.
    expect(setOverride).toHaveBeenLastCalledWith({});
  });

  it("can be started again afterwards", async () => {
    const { view, fake } = setup();
    await act(async () => {
      view.result.current.start();
    });
    for (let step = 0; step < 25; step += 1) {
      await act(async () => {
        vi.advanceTimersByTime(4_000);
      });
    }
    await act(async () => {
      view.result.current.close();
    });
    for (let step = 0; step < 15; step += 1) {
      await act(async () => {
        vi.advanceTimersByTime(4_000);
      });
    }
    expect(view.result.current.phase).toBe("idle");
    await act(async () => {
      view.result.current.start();
    });
    expect(fake.calls.suspend).toBe(2);
  });
});

describe("reduced motion and mobile", () => {
  it("gives the report without the walk, and never suspends the scheduler", async () => {
    const { view, fake } = setup(false);
    await act(async () => {
      view.result.current.start();
    });
    expect(view.result.current.phase).toBe("holding");
    expect(view.result.current.report).not.toBeNull();
    expect(view.result.current.panelOpen).toBe(true);
    // Nothing to suspend: no one is walking anywhere.
    expect(fake.calls.suspend).toBe(0);
    // The whole transcript is available immediately — the information is the
    // point, and withholding it from a reader who asked for stillness would be
    // the accessibility failure, not the animation.
    expect(view.result.current.said).toHaveLength(REPORT_ORDER.length + 1);
  });

  it("closes straight back to idle", async () => {
    const { view } = setup(false);
    await act(async () => {
      view.result.current.start();
      view.result.current.close();
    });
    expect(view.result.current.phase).toBe("idle");
    expect(view.result.current.report).toBeNull();
  });
});

describe("refresh", () => {
  it("rebuilds the report without re-running the meeting", async () => {
    const { view } = setup(false);
    await act(async () => {
      view.result.current.start();
    });
    const before = view.result.current.report;
    await act(async () => {
      view.result.current.refresh();
    });
    expect(view.result.current.report).not.toBe(before);
    expect(view.result.current.phase).toBe("holding");
  });
});
