import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LivePaperLab } from "./live";
vi.mock("@/lib/env", () => ({ API_V1: "https://api.memescope.test/api/v1" }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("reports a disconnected service without inventing balances", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  render(<LivePaperLab />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Trading status cannot be verified",
  );
  expect(screen.queryByText("Available paper cash")).not.toBeInTheDocument();
});
it("shows real scanner state and missing evidence separately from synthetic examples", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        running: true,
        cash_usd: 100,
        realised_usd: 0,
        booked_usd: 0,
        analysis_count: 1,
        heartbeat: { at: "2026-10-13T10:00:00Z", candidates: 1, error: null },
        positions: [],
        trades: [],
        analyses: [
          {
            id: 1,
            at: "2026-10-13T10:00:00Z",
            mint: "mint1",
            action: "SKIP",
            reason: "missing required evidence",
            score: {
              score: 70,
              decision: "INSUFFICIENT_DATA",
              feature_completeness: 0.19,
              reasons: ["No verified sell route"],
            },
          },
        ],
        limitation: "Required gates missing.",
        cost_assumptions: "Estimated costs.",
      }),
    }),
  );
  render(<LivePaperLab />);
  expect(await screen.findByText("Scanner running")).toBeInTheDocument();
  expect(screen.getByText("$100.00")).toBeInTheDocument();
  expect(screen.getByText(/Trained AI model pending/)).toBeInTheDocument();
  expect(screen.getByText(/INSUFFICIENT DATA/)).toBeInTheDocument();
  expect(screen.getByText("No simulated transactions.")).toBeInTheDocument();
});

it("uses the same API origin as the website and includes its session cookie", async () => {
  const request = vi.fn().mockResolvedValue({ ok: false, status: 401 });
  vi.stubGlobal("fetch", request);
  render(<LivePaperLab />);
  expect(await screen.findByRole("alert")).toHaveTextContent("MEMESCOPE access session");
  expect(request).toHaveBeenCalledWith(
    "https://api.memescope.test/api/v1/labs/pretrade-ai/status",
    expect.objectContaining({ credentials: "include" }),
  );
  expect(screen.queryByText("Sign in to view the paper lab.")).not.toBeInTheDocument();
});
