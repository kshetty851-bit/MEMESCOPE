import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LiveUpdatesProvider,
  POLICY_VIOLATION_CODE,
  useLiveUpdates,
} from "@/hooks/use-live-updates";

/**
 * These lock the fix for the public landing page's reconnect loop.
 *
 * The bug: `LiveUpdatesProvider` sat in the root `Providers`, so every
 * anonymous visitor opened a socket the API refuses without an alpha cookie.
 * The refusal closed the socket, the close handler scheduled a reconnect, and
 * the cycle repeated for as long as the tab was open.
 *
 * Two independent guarantees are asserted, because either alone would leave a
 * way back to the loop: the provider can be told not to connect at all, and a
 * refusal on policy grounds is never retried even when it does.
 */

class FakeSocket {
  static instances: FakeSocket[] = [];

  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readonly close = vi.fn();

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  /** Simulates the API refusing the connection with 1008 Policy Violation. */
  refuse() {
    this.onclose?.({ code: POLICY_VIOLATION_CODE });
  }

  /** Simulates a transient drop — a restarted API, a flaky network. */
  drop() {
    this.onclose?.({ code: 1006 });
  }
}

function Probe() {
  const { status } = useLiveUpdates();
  return <span data-testid="status">{status}</span>;
}

function renderProvider(enabled?: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LiveUpdatesProvider enabled={enabled}>
        <Probe />
      </LiveUpdatesProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LiveUpdatesProvider", () => {
  it("opens no socket at all when disabled", async () => {
    renderProvider(false);

    expect(FakeSocket.instances).toHaveLength(0);
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("offline"),
    );
  });

  it("opens exactly one socket when enabled", () => {
    renderProvider(true);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakeSocket.instances[0]?.url).toContain("/api/v1/tokens/stream");
  });

  it("does not reconnect after a policy refusal", async () => {
    renderProvider(true);
    expect(FakeSocket.instances).toHaveLength(1);

    act(() => FakeSocket.instances[0]!.refuse());

    // This is the assertion that matters. Before the fix, the close handler
    // scheduled a reconnect regardless of why the socket closed, so advancing
    // the clock produced socket after socket, forever.
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(FakeSocket.instances).toHaveLength(1);

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("offline"),
    );
  });

  it("still reconnects after a transient drop", async () => {
    renderProvider(true);
    act(() => FakeSocket.instances[0]!.drop());

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("reconnecting"),
    );

    // Backoff is jittered across [0, capped), so the first retry lands well
    // inside this window.
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });

  it("reports offline to consumers with no provider above them", () => {
    render(<Probe />);
    // Screens outside the authenticated shell fall back to polling rather than
    // throwing for want of a provider.
    expect(screen.getByTestId("status")).toHaveTextContent("offline");
  });
});
