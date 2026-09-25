import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();

vi.mock("@/lib/api-client", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}));
const auth = vi.hoisted(() => ({ user: null as null | { role: string } }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

import { FamilyMemberPage } from "./family";

const ADDRESS = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9";

function view(own: object, book: object | null = null) {
  return {
    member: "JAYA", own_wallet: own, own_book: book, enabled: false, ticket_usd: "25", ticket_choices: ["25"],
    combined_cap_usd: "400", deposited_usd: "0", withdrawn_usd: "0", pnl_usd: "0",
    balance_usd: "0", in_trades_usd: "0", available_usd: "0", trades: 0, wins: 0,
    trades_list: [], ledger: [],
  };
}

function page() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FamilyMemberPage member="jaya" />
    </QueryClientProvider>,
  );
}

describe("a family member's own wallet", () => {
  beforeEach(() => window.sessionStorage.setItem("family-token:JAYA", "t"));
  afterEach(() => {
    window.sessionStorage.clear();
    get.mockReset();
    post.mockReset();
    auth.user = null;
  });

  it("shows the address to deposit to, the balance, and that trading is off", async () => {
    get.mockResolvedValue(view({
      address: ADDRESS, explorer: "https://solscan.io/account/x", withdraws_to: "FoHVQyJmv5AHPjccV3BWpMoKiMHLPkF5cfQdqo1nH5TN",
      trading: false, balance_sol: "0.5", balance_usd: "90.00", balance_error: null,
    }));
    page();
    expect(await screen.findByText(ADDRESS)).toBeInTheDocument();
    expect(screen.getByText("0.5000 SOL")).toBeInTheDocument();
    expect(screen.getByText(/Trading: off/)).toBeInTheDocument();
    expect(screen.getByText(/can only go to Karthik/)).toBeInTheDocument();
  });

  it("asks twice before sending, and names only Karthik as the destination", async () => {
    get.mockResolvedValue(view({ address: ADDRESS, trading: false, balance_sol: "0.5" }));
    post.mockResolvedValue({ signature: "sig", explorer: "https://solscan.io/tx/sig", sol: "0.1" });
    page();
    fireEvent.change(await screen.findByLabelText("Amount of SOL to send to Karthik"), {
      target: { value: "0.1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Karthik" }));
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, send 0.1 SOL to Karthik" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body] = post.mock.calls[0]!;
    expect(url).toBe("/real-wallet/family/jaya/withdraw");
    expect(body).toEqual({ sol_amount: "0.1", confirmation_phrase: "WITHDRAW_TO_KARTHIK" });
  });

  it("says so when the member has no wallet yet", async () => {
    get.mockResolvedValue(view({ address: null, trading: false }));
    page();
    expect(await screen.findByText(/own wallet isn.t set up yet/)).toBeInTheDocument();
  });
});

function book(enabled: boolean) {
  return {
    enabled, ticket_usd: "20", ticket_choices: ["10", "20", "50"], today_pnl_usd: "0.00",
    open_positions: 0, since_first_trade: null, trades_list: [],
  };
}

describe("trading from a member's own wallet", () => {
  beforeEach(() => window.sessionStorage.setItem("family-token:JAYA", "t"));
  afterEach(() => {
    window.sessionStorage.clear();
    get.mockReset();
    post.mockReset();
    auth.user = null;
  });

  it("cannot be started from the family password alone", async () => {
    get.mockResolvedValue(view({ address: ADDRESS, balance_sol: "1" }, book(false)));
    page();
    const start = await screen.findByRole("button", { name: "Start trading" });
    expect(start).toBeDisabled();
    expect(screen.getByText(/Only Karthik, signed in, can start this wallet/)).toBeInTheDocument();
  });

  it("starts when Karthik is signed in, at the size he picked", async () => {
    auth.user = { role: "admin" };
    get.mockResolvedValue(view({ address: ADDRESS, balance_sol: "1" }, book(false)));
    post.mockResolvedValue({});
    page();
    fireEvent.change(await screen.findByLabelText("Each trade"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Start trading" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0]![0]).toBe("/real-wallet/family/jaya/own-settings");
    expect(post.mock.calls[0]![1]).toEqual({ enabled: true, ticket_usd: "50" });
  });

  it("can always be stopped", async () => {
    get.mockResolvedValue(view({ address: ADDRESS, balance_sol: "1" }, book(true)));
    post.mockResolvedValue({});
    page();
    expect(await screen.findByText("Trading: on")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop trading" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0]![1]).toEqual({ enabled: false, ticket_usd: "20" });
  });
});
