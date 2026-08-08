import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTokenStream } from "@/hooks/use-token-stream";
import { LiveUpdatesProvider } from "@/hooks/use-live-updates";
import type { DiscoveredToken } from "@/types/api";

/** Minimal WebSocket stand-in that lets tests drive the socket lifecycle. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
    this.onclose?.();
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function token(mint: string, symbol = "TEST"): DiscoveredToken {
  return {
    id: `id-${mint}`,
    mint_address: mint,
    name: `Token ${mint}`,
    symbol,
    decimals: 6,
    metadata_uri: null,
    creator_address: "Wallet1111111111111111111111111111111111111",
    signature: `sig-${mint}`,
    slot: 1,
    block_time: new Date().toISOString(),
    discovered_at: new Date().toISOString(),
    source_program: "pump",
    metadata_status: "resolved",
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return createElement(
    QueryClientProvider,
    { client },
    createElement(LiveUpdatesProvider, null, children),
  );
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useTokenStream", () => {
  it("derives a ws:// URL from the http API origin", () => {
    renderHook(() => useTokenStream(), { wrapper });
    expect(FakeWebSocket.instances[0]!.url).toMatch(/^ws:\/\//);
    expect(FakeWebSocket.instances[0]!.url).toContain("/api/v1/tokens/stream");
  });

  it("reports live status once the socket opens", async () => {
    const { result } = renderHook(() => useTokenStream(), { wrapper });
    expect(result.current.status).toBe("connecting");

    act(() => FakeWebSocket.instances[0]!.onopen?.());
    await waitFor(() => expect(result.current.status).toBe("live"));
  });

  it("prepends discovered tokens so the newest is first", async () => {
    const { result } = renderHook(() => useTokenStream(), { wrapper });
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.onopen?.());

    act(() => socket.emit({ type: "token.discovered", data: token("MintA") }));
    act(() => socket.emit({ type: "token.discovered", data: token("MintB") }));

    await waitFor(() => expect(result.current.tokens).toHaveLength(2));
    expect(result.current.tokens[0]!.mint_address).toBe("MintB");
  });

  it("ignores a duplicate mint replayed after a reconnect", async () => {
    const { result } = renderHook(() => useTokenStream(), { wrapper });
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.onopen?.());

    act(() => socket.emit({ type: "token.discovered", data: token("MintDup") }));
    act(() => socket.emit({ type: "token.discovered", data: token("MintDup") }));

    await waitFor(() => expect(result.current.tokens).toHaveLength(1));
  });

  it("ignores ping and ready frames", async () => {
    const { result } = renderHook(() => useTokenStream(), { wrapper });
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.onopen?.());

    act(() => socket.emit({ type: "connection.ready" }));
    act(() => socket.emit({ type: "ping" }));

    expect(result.current.tokens).toHaveLength(0);
  });

  it("survives a malformed frame", async () => {
    const { result } = renderHook(() => useTokenStream(), { wrapper });
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.onopen?.());

    act(() => socket.onmessage?.({ data: "not json" }));
    act(() => socket.emit({ type: "token.discovered", data: token("MintOk") }));

    await waitFor(() => expect(result.current.tokens).toHaveLength(1));
  });

  it("schedules a reconnect when the socket drops", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useTokenStream(), { wrapper });
      const socket = FakeWebSocket.instances[0]!;
      act(() => socket.onopen?.());
      act(() => socket.onclose?.());

      expect(result.current.status).toBe("reconnecting");

      await act(async () => {
        vi.advanceTimersByTime(31_000);
      });
      expect(FakeWebSocket.instances.length).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("seeds from the initial REST payload", () => {
    const { result } = renderHook(() => useTokenStream([token("Seeded")]), { wrapper });
    expect(result.current.tokens[0]!.mint_address).toBe("Seeded");
  });
});
