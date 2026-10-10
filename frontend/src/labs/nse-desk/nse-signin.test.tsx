import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => auth.value }));

import { NseLabPage } from "./page";

function page() {
  render(<QueryClientProvider client={new QueryClient()}><NseLabPage /></QueryClientProvider>);
}
const base = { login: vi.fn(), error: null, clearError: vi.fn(), isLoading: false };

describe("NSE Lab sign-in", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a sign-in box when signed out, and no question box", () => {
    auth.value = { ...base, isAuthenticated: false, user: null };
    page();
    expect(screen.getByTestId("nse-signin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask Arjun" })).toBeNull();
    expect(screen.getByTestId("nse-say")).toHaveTextContent("Sign in below");
  });

  it("lets the admin ask straight away", () => {
    auth.value = { ...base, isAuthenticated: true, user: { role: "admin" } };
    page();
    expect(screen.queryByTestId("nse-signin")).toBeNull();
    expect(screen.getByRole("button", { name: "Ask Arjun" })).toBeInTheDocument();
  });

  it("turns away a signed-in account that is not the admin", () => {
    auth.value = { ...base, isAuthenticated: true, user: { role: "user" } };
    page();
    expect(screen.getByTestId("nse-say")).toHaveTextContent("only work for Karthik");
    expect(screen.queryByRole("button", { name: "Ask Arjun" })).toBeNull();
  });
});
