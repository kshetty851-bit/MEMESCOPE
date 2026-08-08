import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlphaAccess } from "@/components/alpha/alpha-access";
import { ALPHA_ACCESS } from "@/lib/env";
import { api } from "@/lib/api-client";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

vi.mock("@/lib/api-client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("AlphaAccess", () => {
  it("refuses an incorrect code without storing access", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });
    vi.mocked(api.post).mockRejectedValue(new Error("denied"));

    render(<AlphaAccess onUnlocking={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() => {
      expect(screen.getByText("Access code not recognised.")).toBeInTheDocument();
    });
    expect(window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey)).toBeNull();
  });

  it("remembers a server-accepted code and enters the command center", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });
    vi.mocked(api.post).mockResolvedValue({
      authenticated: true,
      expires_at: "2026-09-07T00:00:00Z",
    });
    const onUnlocking = vi.fn();
    render(<AlphaAccess onUnlocking={onUnlocking} />);

    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "619554" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() => {
      expect(window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey)).toBe("true");
    });
    expect(api.post).toHaveBeenCalledWith(
      "/alpha/unlock",
      { code: "619554" },
      { skipAuthRetry: true },
    );
    expect(onUnlocking).toHaveBeenCalledWith(true);

    await waitFor(
      () => {
        expect(push).toHaveBeenCalledWith("/command");
      },
      { timeout: 2500 },
    );
  });

  it("skips the form when the server reports an alpha session", async () => {
    vi.mocked(api.get).mockResolvedValue({
      authenticated: true,
      expires_at: "2026-09-07T00:00:00Z",
    });

    render(<AlphaAccess onUnlocking={vi.fn()} />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/command"));
  });
});
