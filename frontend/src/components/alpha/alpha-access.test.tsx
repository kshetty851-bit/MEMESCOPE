import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlphaAccess } from "@/components/alpha/alpha-access";
import { ALPHA_ACCESS } from "@/lib/env";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("AlphaAccess", () => {
  it("refuses an incorrect code without storing access", () => {
    render(<AlphaAccess onUnlocking={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(screen.getByText("Access code not recognised.")).toBeInTheDocument();
    expect(window.localStorage.getItem(ALPHA_ACCESS.storageKey)).toBeNull();
  });

  it("remembers a correct code and enters the command center", async () => {
    vi.useFakeTimers();
    const onUnlocking = vi.fn();
    render(<AlphaAccess onUnlocking={onUnlocking} />);

    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: ALPHA_ACCESS.code },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(onUnlocking).toHaveBeenCalledWith(true);
    expect(window.localStorage.getItem(ALPHA_ACCESS.storageKey)).toBe("granted");
    expect(window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey)).toBe("true");

    act(() => vi.advanceTimersByTime(1700));
    expect(push).toHaveBeenCalledWith("/command");
  });

  it("skips the form when this browser has already unlocked alpha access", async () => {
    window.localStorage.setItem(ALPHA_ACCESS.storageKey, "granted");

    render(<AlphaAccess onUnlocking={vi.fn()} />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/command"));
  });
});
