import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type * as ApiClientModule from "@/lib/api-client";
import { api } from "@/lib/api-client";

import { FreshHeld } from "./page";
import type { FreshHeld as FreshHeldData } from "./types";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClientModule>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(cleanup);

/** The fresh $500 BASE 75k book as prod served it, 19 Sep 15:00 UTC. */
const HELD: FreshHeldData = {
  book: "BASE_75k_5m",
  ticket_usd: "100",
  capital_usd: "500",
  read_at: "2026-09-19T15:00:00Z",
  sold_usd: "1020.93",
  held_usd: "1100.34",
  unreadable: 1,
  wallet_trades: 5,
  wallet_held_usd: "579.77",
  rows: [
    { mint: "7aFiJoPhd7Vc8CH4WPx2cXpJiXGePfck26XkDwGpump", symbol: "POKEMON",
      opened_at: "2026-09-19T13:14:36Z", closed_at: "2026-09-19T13:19:39Z",
      sold_usd: "104.88", held_usd: "152.27", depth_usd: "132880" },
    { mint: "Bu11jakMint111111111111111111111111111pump", symbol: "Bulljak",
      opened_at: "2026-09-19T14:54:00Z", closed_at: "2026-09-19T14:56:00Z",
      sold_usd: "8.83", held_usd: null, depth_usd: null },
  ],
};

it("shows what every closed coin is worth if it had never been sold", async () => {
  vi.mocked(api.get).mockResolvedValue(HELD);
  render(<FreshHeld book="BASE_75k_5m" />, { wrapper });

  expect(await screen.findByText(/held until now/i)).toBeInTheDocument();
  expect(vi.mocked(api.get)).toHaveBeenCalledWith(
    "/labs/graduation/fresh/held?book=BASE_75k_5m");
  expect(screen.getByText("Sold: $1,020.93")).toBeInTheDocument();
  expect(screen.getByText(/Held: \$1,100\.34 \(\+\$79\.41\)/)).toBeInTheDocument();
  expect(screen.getByText("POKEMON")).toBeInTheDocument();
  expect(screen.getByText("$152.27")).toBeInTheDocument();
  expect(screen.getByText("+$47.39")).toBeInTheDocument();
  // An unreadable pool is said, not priced.
  expect(screen.getByText("unread")).toBeInTheDocument();
  expect(screen.getByText(/first\s+5 coins: \$579\.77 now/)).toBeInTheDocument();
});
