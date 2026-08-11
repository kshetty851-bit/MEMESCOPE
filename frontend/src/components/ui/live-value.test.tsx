import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveValue } from "@/components/ui/live-value";
import { MOTION } from "@/lib/motion";

/**
 * The flash, driven directly.
 *
 * The browser cannot verify this: the preview pane never refetches, so no data
 * change ever reaches the component there. Driving the prop is the decisive
 * test, and it also pins the two behaviours most likely to regress into noise —
 * flashing on mount, and flashing on a change too small to render.
 */

// Reads the semantic tokens, not the deprecated `safe`/`danger` aliases the
// component used before the Phase 7 migration.
const wash = (el: HTMLElement) =>
  /bg-up\//.test(el.className)
    ? "up"
    : /bg-down\//.test(el.className)
      ? "down"
      : "none";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("LiveValue", () => {
  it("does not flash on first render", () => {
    // Ten rows lighting up on page load would teach the eye to ignore the
    // signal exactly when it starts carrying information.
    render(<LiveValue value="10" display="$10" />);
    expect(wash(screen.getByText("$10"))).toBe("none");
  });

  it("washes green when the value rises", () => {
    const { rerender } = render(<LiveValue value="10" display="$10" />);
    act(() => {
      rerender(<LiveValue value="12" display="$12" />);
    });
    expect(wash(screen.getByText("$12"))).toBe("up");
  });

  it("washes red when the value falls", () => {
    const { rerender } = render(<LiveValue value="10" display="$10" />);
    act(() => {
      rerender(<LiveValue value="8" display="$8" />);
    });
    expect(wash(screen.getByText("$8"))).toBe("down");
  });

  it("clears itself so a run of ticks reads as activity, not a strobe", () => {
    const { rerender } = render(<LiveValue value="10" display="$10" />);
    act(() => {
      rerender(<LiveValue value="12" display="$12" />);
    });
    expect(wash(screen.getByText("$12"))).toBe("up");

    act(() => {
      vi.advanceTimersByTime(MOTION.flash + 20);
    });
    expect(wash(screen.getByText("$12"))).toBe("none");
  });

  it("does not flash when a re-render carries the same value", () => {
    const { rerender } = render(<LiveValue value="10" display="$10" />);
    act(() => {
      rerender(<LiveValue value="10" display="$10" />);
    });
    expect(wash(screen.getByText("$10"))).toBe("none");
  });

  it("detects a change the formatted output hides", () => {
    // Both render as "$0.0000". Comparing display text would miss this
    // entirely — which is why the raw figure is passed separately.
    const { rerender } = render(
      <LiveValue value="0.0000123" display="$0.0000" />,
    );
    act(() => {
      rerender(<LiveValue value="0.0000456" display="$0.0000" />);
    });
    expect(wash(screen.getByText("$0.0000"))).toBe("up");
  });

  it("does not flash when a token stops being priced", () => {
    // A token that lost its pool has not gone down.
    const { rerender } = render(<LiveValue value="10" display="$10" />);
    act(() => {
      rerender(<LiveValue value={null} display={null} />);
    });
    expect(wash(screen.getByText("—"))).toBe("none");
  });

  it("renders a dash rather than an empty cell when there is nothing to show", () => {
    render(<LiveValue value={null} display={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
