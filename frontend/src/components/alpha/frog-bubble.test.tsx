import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FrogBubble } from "./frog-bubble";

describe("the frog's bubble at launch", () => {
  it("says access approved, shouts the countdown and cheers — silently", () => {
    const speak = vi.fn();
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn(), getVoices: () => [] });
    const { rerender, container } = render(<FrogBubble phase="approved" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("Access approved, Captain!");
    for (const n of [5, 4, 3, 2, 1]) rerender(<FrogBubble phase="countdown" count={n} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("1!");
    rerender(<FrogBubble phase="ignition" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("WOO-HOO!");
    // Karthik asked for a silent launch (2026-09-25).
    expect(speak).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("says nothing before a code is accepted", () => {
    const { container } = render(<FrogBubble phase="idle" count={null} />);
    expect(container.querySelector(".frog-bubble")).toBeNull();
  });
});
