import { describe, expect, it } from "vitest";

import {
  EVENT_CAP,
  EVENT_KINDS,
  EVENT_WINDOW_MS,
  createEventMeter,
  emptyActivity,
  kindOf,
} from "@/lib/hq/events";

/**
 * Storm protection, as a property rather than as a hope.
 *
 * MEMESCOPE's stream is measured in tens of events a second during enrichment.
 * The thing being defended here is not CPU — it is that HQ must remain
 * *correct* while discarding almost everything it is told. A desk under a
 * hundred events a second and a desk under thirty are the same fact, and the
 * meter's job is to report that fact without ever holding a hundred anything.
 */

const T = 1_760_000_000_000;

describe("the event meter", () => {
  it("reads a storm as one busy desk rather than as a queue of reactions", () => {
    const meter = createEventMeter(T - EVENT_WINDOW_MS);
    for (let i = 0; i < 100; i += 1) meter.record("market.changed", T + i * 30);

    const snapshot = meter.snapshot(T + 3_000);
    expect(snapshot.counts.market).toBe(100);
    // One reading. Whatever the office does with it, it does once.
    expect(Object.keys(snapshot.counts)).toHaveLength(EVENT_KINDS.length);
  });

  it("bounds what it keeps, however long the storm runs", () => {
    const meter = createEventMeter(T - EVENT_WINDOW_MS);
    for (let i = 0; i < 5_000; i += 1) meter.record("market.changed", T + i);
    expect(meter.snapshot(T + 5_000).counts.market).toBeLessThanOrEqual(EVENT_CAP);
  });

  it("forgets what no longer describes now", () => {
    const meter = createEventMeter(T - EVENT_WINDOW_MS);
    meter.record("token.discovered", T);
    expect(meter.snapshot(T + 1_000).counts.discovery).toBe(1);
    expect(meter.snapshot(T + EVENT_WINDOW_MS + 1).counts.discovery).toBe(0);
  });

  it("remembers when a kind was last seen even after the window drops it", () => {
    const meter = createEventMeter(T - EVENT_WINDOW_MS);
    meter.record("paper.changed", T);
    const later = meter.snapshot(T + EVENT_WINDOW_MS * 2);
    expect(later.counts.paper).toBe(0);
    expect(later.lastAt.paper).toBe(T);
  });

  it("refuses to call a zero quiet until it has listened for a full window", () => {
    // A count of zero one second after mount says nothing about the system.
    // Reporting it as quiet would be the fastest possible way to invent calm.
    const meter = createEventMeter(T);
    expect(meter.snapshot(T + 1_000).settled).toBe(false);
    expect(meter.snapshot(T + EVENT_WINDOW_MS).settled).toBe(true);
  });

  it("ignores anything it does not recognise", () => {
    const meter = createEventMeter(T - EVENT_WINDOW_MS);
    meter.record("something.invented", T);
    meter.record("real_wallet.changed", T);
    const snapshot = meter.snapshot(T);
    for (const kind of EVENT_KINDS) expect(snapshot.counts[kind], kind).toBe(0);
  });

  it("maps exactly the stream events HQ is allowed to read", () => {
    expect(kindOf("token.discovered")).toBe("discovery");
    expect(kindOf("market.changed")).toBe("market");
    expect(kindOf("score.changed")).toBe("score");
    expect(kindOf("radar.score_updated")).toBe("score");
    expect(kindOf("radar.changed")).toBe("radar");
    expect(kindOf("paper.changed")).toBe("paper");

    // Real Wallet is the Vault's subject and nobody else's. A mapping here
    // would be the shortest path from a real transfer to a cartoon reacting to
    // it, and this assertion exists to make adding one a deliberate act.
    expect(kindOf("real_wallet.changed")).toBeNull();
    expect(kindOf("real_wallet.dry_run.changed")).toBeNull();
  });

  it("starts empty and unsettled", () => {
    const blank = emptyActivity();
    expect(blank.settled).toBe(false);
    for (const kind of EVENT_KINDS) {
      expect(blank.counts[kind]).toBe(0);
      expect(blank.lastAt[kind]).toBeNull();
    }
  });
});
