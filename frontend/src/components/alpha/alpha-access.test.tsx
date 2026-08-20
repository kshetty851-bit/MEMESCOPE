import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlphaAccess } from "@/components/alpha/alpha-access";
import { ALPHA_ACCESS } from "@/lib/env";
import { ApiError, api } from "@/lib/api-client";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

vi.mock("@/lib/api-client", () => ({
  ApiError: class ApiError extends Error {
    constructor(readonly status: number) {
      super("request failed");
    }
  },
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

    const onPhase = vi.fn();
    render(<AlphaAccess onPhase={onPhase} />);

    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() => {
      expect(screen.getByText("Access code not recognised.")).toBeInTheDocument();
    });
    expect(window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey)).toBeNull();
    // A refused code must never start the launch.
    expect(onPhase).toHaveBeenCalledWith("denied");
    expect(onPhase).not.toHaveBeenCalledWith("approved");
  });

  it("does not mislabel a temporary upstream failure as an incorrect code", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });
    vi.mocked(api.post).mockRejectedValue(new ApiError(503, "upstream", "Unavailable"));

    render(<AlphaAccess onPhase={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() => {
      expect(
        screen.getByText("Access service is temporarily unavailable. Please retry."),
      ).toBeInTheDocument();
    });
  });

  it("remembers a server-accepted code and enters the command center", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });
    vi.mocked(api.post).mockResolvedValue({
      authenticated: true,
      expires_at: "2026-09-07T00:00:00Z",
    });
    const onPhase = vi.fn();
    render(<AlphaAccess onPhase={onPhase} />);

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
    expect(onPhase).toHaveBeenCalledWith("validating");
    expect(onPhase).toHaveBeenCalledWith("approved");
  });

  it("locks the form once a code is accepted", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });
    vi.mocked(api.post).mockResolvedValue({
      authenticated: true,
      expires_at: "2026-09-07T00:00:00Z",
    });

    render(<AlphaAccess onPhase={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Enter access code"), {
      target: { value: "619554" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    // No path back to an editable field: the launch plays over a locked form,
    // so a second code cannot be submitted while the first one is in the air.
    await waitFor(() => {
      expect(screen.getByLabelText("Enter access code")).toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlocking…" }));
    expect(api.post).toHaveBeenCalledTimes(2); // the unlock and its activity ping, nothing more
  });

  it("skips the form when the server reports an alpha session", async () => {
    /**
     * This asserted `replace("/command")` — the auto-redirect. It was correct
     * while the homepage was only a gate, and it is the reason nobody could
     * see the crew section: a returning visitor was navigated off the page
     * before it finished painting.
     *
     * The *intent* survives and is what is asserted now: somebody already in
     * does not get asked for a code again. What changed is that they are no
     * longer thrown off the front page of the product to prove it.
     */
    vi.mocked(api.get).mockResolvedValue({
      authenticated: true,
      expires_at: "2026-09-07T00:00:00Z",
    });

    render(<AlphaAccess onPhase={vi.fn()} />);

    await waitFor(() =>
      expect(screen.queryByPlaceholderText("Access code")).not.toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("a visitor who is already in", () => {
  /**
   * The bug this covers: the card used to `router.replace` to the dashboard
   * the instant the session check said authenticated, so a returning visitor
   * never saw the homepage — they typed the address and arrived in the
   * Scanner. The team section could not be seen no matter where it sat.
   */
  it("stays on the homepage and offers a door instead of redirecting", async () => {
    vi.mocked(api.get).mockResolvedValue({
      authenticated: true,
      expires_at: "2099-01-01T00:00:00Z",
    });

    render(<AlphaAccess onPhase={() => {}} />);

    const enter = await screen.findByTestId("alpha-enter-terminal");
    expect(enter).toHaveAttribute("href", ALPHA_ACCESS.dashboardPath);
    // Nothing navigated on its own. That is the whole fix.
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("still shows the code form to a visitor who is not signed in", async () => {
    vi.mocked(api.get).mockResolvedValue({ authenticated: false, expires_at: null });

    render(<AlphaAccess onPhase={() => {}} />);

    // The gate is untouched: no session means the code form, every time.
    expect(await screen.findByPlaceholderText("Access code")).toBeInTheDocument();
    expect(screen.queryByTestId("alpha-enter-terminal")).not.toBeInTheDocument();
  });

  it("shows the form rather than a door when the session check fails", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("offline"));

    render(<AlphaAccess onPhase={() => {}} />);

    // Fail closed. An unreachable session endpoint must never be read as
    // "already in" — that would hand the terminal link to a stranger.
    expect(await screen.findByPlaceholderText("Access code")).toBeInTheDocument();
    expect(screen.queryByTestId("alpha-enter-terminal")).not.toBeInTheDocument();
  });
});
