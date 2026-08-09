import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TesterActivityPage from "@/app/(dashboard)/tester-activity/page";
import { api } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ api: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TesterActivityPage", () => {
  it("does not reveal activity data when the protected API rejects the request", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("forbidden"));
    render(<TesterActivityPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("Restricted")).toBeInTheDocument());
    expect(screen.queryByText("Active now")).not.toBeInTheDocument();
  });

  it("renders anonymous session data supplied by the protected API", async () => {
    vi.mocked(api.get).mockResolvedValue({
      active_now: 1,
      seen_today: 2,
      sessions: [
        {
          session_id: "4e7b4fd7-4fb8-4cd9-92ec-4a68bf128d0c",
          unlocked_at: "2026-08-09T09:00:00Z",
          last_seen_at: "2026-08-09T09:01:00Z",
          current_path: "/wallet",
          status: "active",
        },
      ],
    });
    render(<TesterActivityPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("4e7b4fd7")).toBeInTheDocument());
    expect(screen.getByText("4e7b4fd7")).toBeInTheDocument();
    expect(screen.getByText("/wallet")).toBeInTheDocument();
  });
});
