import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityHeartbeat } from "@/components/alpha/activity-heartbeat";
import { api } from "@/lib/api-client";

vi.mock("next/navigation", () => ({
  usePathname: () => "/wallet",
}));

vi.mock("@/lib/api-client", () => ({
  api: { post: vi.fn().mockResolvedValue(undefined) },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("ActivityHeartbeat", () => {
  it("reports only the current route on its lightweight cadence", async () => {
    vi.useFakeTimers();
    render(<ActivityHeartbeat />);

    expect(api.post).toHaveBeenCalledWith(
      "/alpha/activity",
      { path: "/wallet" },
      { skipAuthRetry: true },
    );

    await vi.advanceTimersByTimeAsync(25_000);
    expect(api.post).toHaveBeenCalledTimes(2);
  });
});
