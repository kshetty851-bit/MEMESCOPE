import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-client";
import { isAlreadyWatched, isUnpersistedAccount } from "@/lib/watchlist";
import {
  TRENDING_SORTS,
  TRENDING_SORT_LABEL,
  isTrendingSort,
} from "@/lib/market";

/**
 * Watchlists are the first user-owned resource in MEMESCOPE, so they are the
 * first surface that can fail for reasons which are neither the user's fault
 * nor a bug. These pin the two 409s apart, because they need opposite handling:
 * one is a configuration state to explain, the other is the outcome the caller
 * already wanted.
 */

const conflict = (message: string) => new ApiError(409, "conflict", message);

describe("isUnpersistedAccount", () => {
  it("recognises the auth-bypass conflict", () => {
    expect(
      isUnpersistedAccount(
        conflict(
          "Watchlists belong to a real account, and this request is authenticated " +
            "by the development auth bypass, whose principal is never persisted.",
        ),
      ),
    ).toBe(true);
  });

  it("does not claim every 409 is a configuration problem", () => {
    expect(isUnpersistedAccount(conflict("That token is already on this watchlist."))).toBe(
      false,
    );
    expect(isUnpersistedAccount(conflict("You already have a watchlist called 'x'."))).toBe(
      false,
    );
  });

  it("ignores other statuses and non-errors", () => {
    expect(isUnpersistedAccount(new ApiError(500, "boom", "real account"))).toBe(false);
    expect(isUnpersistedAccount(new Error("real account"))).toBe(false);
    expect(isUnpersistedAccount(null)).toBe(false);
  });
});

describe("isAlreadyWatched", () => {
  it("recognises a duplicate add", () => {
    expect(isAlreadyWatched(conflict("That token is already on this watchlist."))).toBe(
      true,
    );
  });

  it("does not swallow the account conflict", () => {
    // Treating this one as benign would silently drop the only message that
    // explains why nothing can be saved.
    expect(
      isAlreadyWatched(conflict("Watchlists belong to a real account…")),
    ).toBe(false);
  });
});

describe("trending sorts", () => {
  it("matches the backend's TrendingSort literal exactly", () => {
    expect([...TRENDING_SORTS]).toEqual([
      "volume_24h",
      "volume_1h",
      "volume_5m",
      "liquidity_usd",
      "market_cap",
      "price_usd",
      "captured_at",
    ]);
  });

  it("labels every sort it accepts", () => {
    for (const sort of TRENDING_SORTS) {
      expect(TRENDING_SORT_LABEL[sort]).toBeTruthy();
    }
  });

  it("rejects a sort the endpoint would refuse", () => {
    // The API validates against the same literal; sending anything else is a
    // 422 the user would see as a broken screen.
    expect(isTrendingSort("volume_24h")).toBe(true);
    expect(isTrendingSort("momentum")).toBe(false);
    expect(isTrendingSort("score")).toBe(false);
  });
});
