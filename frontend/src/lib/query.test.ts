import { describe, expect, it } from "vitest";

import { ERROR_RETRY_MS, livePoll } from "@/lib/query";

/**
 * The stuck "Signal lost" screen.
 *
 * A real Postgres outage made every paper-wallet query fail. The database
 * recovered minutes later and the API returned 200 for every request after
 * that — but an open tab stayed on the error indefinitely, because with the
 * live stream connected `refetchInterval` was `false`, the query had already
 * exhausted its two retries, and nothing was left to try again.
 *
 * Meanwhile the screen said "this view will recover on its own."
 *
 * These pin the rule that makes that sentence true.
 */

const query = (status: string) => ({ state: { status } });

const POLL = 120_000;

describe("livePoll", () => {
  it("does not poll while the stream is live and the query is healthy", () => {
    // The socket pushes invalidations, so a timer would just duplicate it.
    expect(livePoll("live", POLL)(query("success"))).toBe(false);
  });

  it("polls at the data cadence when the stream is offline", () => {
    expect(livePoll("offline", POLL)(query("success"))).toBe(POLL);
    expect(livePoll("connecting", POLL)(query("success"))).toBe(POLL);
    expect(livePoll("reconnecting", POLL)(query("success"))).toBe(POLL);
  });

  it("keeps retrying an errored query even while the stream is live", () => {
    // The bug: this returned `false`, so a transient backend failure became a
    // permanent error state for as long as the tab stayed open.
    expect(livePoll("live", POLL)(query("error"))).toBe(ERROR_RETRY_MS);
  });

  it("retries an errored query when the stream is offline too", () => {
    expect(livePoll("offline", POLL)(query("error"))).toBe(ERROR_RETRY_MS);
  });

  it("recovers faster than the data cadence", () => {
    // A broken screen should come back quickly; a working one need not ask.
    expect(ERROR_RETRY_MS).toBeLessThan(POLL);
  });

  it("returns to the stream-aware cadence once a fetch succeeds", () => {
    const poll = livePoll("live", POLL);
    expect(poll(query("error"))).toBe(ERROR_RETRY_MS);
    expect(poll(query("success"))).toBe(false);
  });

  it("treats a pending query as healthy rather than retrying it", () => {
    expect(livePoll("live", POLL)(query("pending"))).toBe(false);
  });
});
