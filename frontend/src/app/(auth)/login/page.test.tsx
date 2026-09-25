import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/(auth)/login/page";
import { useAuthStore } from "@/stores/auth-store";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

function signedInAt(url: string) {
  window.history.pushState({}, "", url);
  useAuthStore.setState({
    status: "authenticated",
    user: {
      id: "u-1",
      email: "owner@example.com",
      display_name: "Owner",
      role: "admin",
      is_active: true,
      is_verified: true,
      last_login_at: null,
      created_at: new Date(0).toISOString(),
    },
  });
  render(<LoginPage />);
}

afterEach(() => {
  cleanup();
  replace.mockClear();
  useAuthStore.setState({ status: "unauthenticated", user: null });
  window.history.pushState({}, "", "/");
});

describe("LoginPage return path", () => {
  it("goes back to the page that sent you here", async () => {
    signedInAt("/login?next=/real-wallet");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/real-wallet"));
  });

  it.each([
    "/login?next=//evil.example",
    "/login?next=https://evil.example",
    "/login?next=/%5Cevil.example",
    "/login?next=javascript:alert(1)",
    "/login",
  ])("never leaves the site: %s", async (url) => {
    signedInAt(url);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/karthik-lab"));
  });
});
