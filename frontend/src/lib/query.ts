import type { LiveStreamStatus } from "@/hooks/use-live-updates";

/**
 * POLLING CADENCE, INCLUDING WHEN THINGS ARE BROKEN.
 *
 * Every data hook used to write this inline:
 *
 *     refetchInterval: status === "live" ? false : POLL_MS
 *
 * The intent was right — with a live stream pushing invalidations, polling is
 * redundant, so the socket replaces the timer. The failure mode was not.
 *
 * A query that errors retries twice (see the client's `retry` rule) and then
 * stops. With `refetchInterval: false` there is no timer left to try again, so
 * the error is **permanent** until the component remounts or the socket happens
 * to invalidate that exact key. A backend blip of thirty seconds left the paper
 * wallet showing "Signal lost" indefinitely, on a screen whose own copy reads
 * *"this view will recover on its own."*
 *
 * It did not recover on its own. This is what makes that sentence true: while a
 * query is in an error state it always polls, regardless of the stream, and it
 * returns to the stream-aware cadence the moment a fetch succeeds.
 *
 * The recovery interval is deliberately much shorter than the data cadence.
 * A broken screen should come back quickly; a working one does not need to ask.
 */

/** How often to re-attempt a query that is currently failing. */
export const ERROR_RETRY_MS = 15_000;

/**
 * The only thing this needs from a query: whether it is currently failing.
 *
 * Structural rather than `Query<TQueryFnData, …>` on purpose. Naming the full
 * generic forced `unknown` into `useQuery`'s inference at every call site and
 * collapsed `data` to `{}` — so the fix for a stuck error state would have
 * broken the type of every screen that consumed one.
 */
export interface PollableQuery {
  state: { status: string };
}

/**
 * `refetchInterval` for a query whose freshness is normally pushed by the live
 * stream.
 *
 * @param status  the live stream's current state
 * @param base    the polling cadence to use when the stream is not connected
 */
export function livePoll(
  status: LiveStreamStatus,
  base: number,
): (query: PollableQuery) => number | false {
  return (query) => {
    // Broken beats everything. Without this branch a live socket silently
    // guarantees the error can never clear.
    if (query.state.status === "error") return ERROR_RETRY_MS;
    return status === "live" ? false : base;
  };
}
