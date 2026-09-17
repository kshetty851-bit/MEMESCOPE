import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api-client";

import { fetchPaperTrades } from "./api";

vi.mock("@/lib/api-client", () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }));

describe("fetchPaperTrades", () => {
  it("asks for the wallet size the board is set to", async () => {
    await fetchPaperTrades("B3_198k_4m", { ticket: 10, split: 10 });
    expect(api.get).toHaveBeenCalledWith(
      "/labs/graduation/paper/trades?book=B3_198k_4m&ticket=10&split=10",
    );
  });

  it("omits the size when none is chosen, so the book answers as before", async () => {
    await fetchPaperTrades("B3_198k_4m");
    expect(api.get).toHaveBeenLastCalledWith(
      "/labs/graduation/paper/trades?book=B3_198k_4m",
    );
  });
});
