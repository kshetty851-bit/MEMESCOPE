import { describe, expect, it } from "vitest";

import {
  OPERATIONAL_STATES,
  STALE_AFTER_MS,
  THRESHOLDS,
  deriveHqState,
  fresh,
  isSecurityGated,
  react,
  witness,
  type HqSources,
  type Source,
} from "@/lib/hq/adapter";
import { createEventMeter, emptyActivity, kindOf, type EventActivity } from "@/lib/hq/events";
import { EMPLOYEES, type EmployeeId, type EmployeeState } from "@/lib/hq/employees";
import type { PipelineHealth, StageStatus, TokenSecuritySummary } from "@/lib/hq/pipeline";
import type { PaperAudit, PaperPositions, PaperWallet } from "@/types/paper";
import type { RadarPerformance } from "@/types/radar";

/**
 * HQ-4 acceptance.
 *
 * The office is charming, and a charming thing that is wrong is worse than an
 * ugly thing that is right. Almost every test in this file is a variation on
 * one question: when MEMESCOPE cannot answer, does HQ shut up, or does it keep
 * smiling? A green room over a dead backend is the single failure this feature
 * cannot survive, so the fail-closed cases are asserted first, exhaustively,
 * and for every employee rather than for a representative one.
 */

const NOW = 1_760_000_000_000;

/* ── fixtures ────────────────────────────────────────────────────────── */

/**
 * Cast rather than fully literal on purpose.
 *
 * `types/paper.ts` is being actively extended by other work. A test that spelled
 * out every field would break on somebody else's unrelated addition, which
 * trains people to edit tests to make them pass — the worst habit a suite can
 * teach.
 */
function pipeline(overrides: {
  scanner?: Partial<PipelineHealth["scanner"]>;
  market?: Partial<PipelineHealth["market_enrichment"]>;
  scoring?: Partial<PipelineHealth["scoring"]>;
  overall?: StageStatus;
} = {}): PipelineHealth {
  return {
    scanner: {
      status: "healthy",
      last_discovery: null,
      minutes_since_last_token: 4,
      reconnect_attempts: 0,
      failure_reason: null,
      ...overrides.scanner,
    },
    market_enrichment: {
      status: "healthy",
      last_snapshot: null,
      minutes_since_last_snapshot: 0.4,
      queue_depth: 0,
      dead_lettered: 0,
      priority_queue_depth: 0,
      priority_tokens: 12,
      oldest_priority_wait_seconds: null,
      oldest_normal_wait_seconds: null,
      tracked_freshness_p50_seconds: 40,
      tracked_freshness_p95_seconds: 90,
      tracked_freshness_worst_seconds: 120,
      tracked_stale_count: 0,
      ...overrides.market,
    },
    scoring: {
      status: "healthy",
      last_score: null,
      minutes_since_last_score: 1,
      pending: 0,
      ...overrides.scoring,
    },
    radar: {
      status: "healthy",
      last_cycle: null,
      minutes_since_last_cycle: 2,
      tracked_tokens: 30,
    },
    overall: overrides.overall ?? "healthy",
    environment: "development",
    version: "0.8.0",
    observed_at: new Date(NOW).toISOString(),
  };
}

function wallet(metrics: Record<string, unknown> = {}, enabled = true): PaperWallet {
  return {
    enabled,
    metrics: {
      open_positions: 0,
      closed_positions: 0,
      invested_usd: "0",
      open_value: "0",
      unpriced_positions: 0,
      realised_pnl: "0",
      win_rate_pct: null,
      profit_factor: null,
      max_drawdown_pct: null,
      ...metrics,
    },
  } as unknown as PaperWallet;
}

function positions(count = 0): PaperPositions {
  return {
    items: Array.from({ length: count }, (_, i) => ({ mint_address: `mint-${i}` })),
    enabled: true,
  } as unknown as PaperPositions;
}

function audit(total = 0, net: string | null = null): PaperAudit {
  return {
    total,
    items: net === null ? [] : [{ net_return_usd: net, exit_reason: "target" }],
    enabled: true,
  } as unknown as PaperAudit;
}

function performance(total = 120): RadarPerformance {
  return { total_opportunities: total, active_opportunities: 12, success_rate: "0.31" } as unknown as RadarPerformance;
}

function at<T>(data: T, observedAt = NOW): Source<T> {
  return { data, observedAt };
}

/** A meter that has been listening long enough for a zero to mean something. */
function activity(counts: Partial<EventActivity["counts"]> = {}): EventActivity {
  return { ...emptyActivity(), counts: { ...emptyActivity().counts, ...counts }, settled: true };
}

/**
 * A live token-security summary. Defaults to the state the platform is
 * actually in as of HQ-6: evaluations happening, nothing positively unsafe,
 * and most tokens unverifiable because liquidity security is unproven.
 */
function security(overrides: Partial<TokenSecuritySummary> = {}): TokenSecuritySummary {
  return {
    window_hours: 24,
    evaluator_version: "1.0.0",
    evaluated_recently: 12,
    verified_count: 0,
    failed_count: 0,
    unknown_count: 12,
    failures_by_reason: {},
    last_evaluation_at: new Date(NOW).toISOString(),
    total_evaluations: 120,
    source_state: "live",
    observed_at: new Date(NOW).toISOString(),
    ...overrides,
  };
}

/**
 * A healthy operations reading.
 *
 * Added to `build` when the operations surface shipped. Before it existed, the
 * reliability trio read UNKNOWN-and-unsourced and could not affect anything;
 * now that `GET /hq` is real, an absent operations source means three
 * departments that stopped reporting, which Nova is *supposed* to notice. So
 * the default has to be a live one, and the tests that care about absence
 * override it explicitly.
 */
function operations(overrides: Record<string, unknown> = {}) {
  const component = (name: string) => ({
    component: name,
    status: "healthy" as const,
    detail: "ok",
    latency_ms: 1,
    measured: true,
  });
  return {
    health: {
      disk: {
        status: "healthy" as const,
        percent_used: 20,
        warning_percent: 75,
        critical_percent: 85,
        measured: true,
        detail: "20% used.",
      },
      redis: component("redis"),
      database: component("database"),
      worker: {
        status: "healthy" as const,
        nodes: ["celery@a"],
        replies: 1,
        measured: true,
        detail: "1 worker answered a ping.",
      },
      scheduler: {
        status: "healthy" as const,
        last_beat: new Date(NOW).toISOString(),
        seconds_since_beat: 12,
        expected_within_seconds: 200,
        measured: true,
        detail: "Last scheduler beat 12s ago.",
      },
      queues: {
        status: "healthy" as const,
        depths: { celery: 0 },
        total: 0,
        measured: true,
        detail: "0 messages waiting on the broker.",
      },
      overall: "healthy" as const,
      unmeasured: 0,
      environment: "test",
      version: "0.0.0",
      observed_at: new Date(NOW).toISOString(),
    },
    incidents: [],
    recent: [],
    activity: [],
    allowlist: [],
    invariants: { digest: "abc123", values: {} },
    ...overrides,
  };
}

function build(overrides: Partial<HqSources> = {}) {
  return deriveHqState({
    operations: at(operations() as never),
    pipeline: at(pipeline()),
    paperWallet: at(wallet()),
    paperPositions: at(positions()),
    paperAudit: at(audit()),
    radarPerformance: at(performance()),
    tokenSecurity: at(security()),
    activity: activity(),
    stream: "live",
    transients: {},
    now: NOW,
    ...overrides,
  });
}

/* ── the rule that outranks every other rule ─────────────────────────── */

describe("fail-closed", () => {
  it("claims nothing at all with no sources", () => {
    const state = deriveHqState();
    for (const employee of EMPLOYEES) {
      expect(state.employees[employee.id].state, employee.id).toBe("unknown");
    }
    expect(state.activity).toBe("UNKNOWN");
  });

  it("turns a null pipeline into UNKNOWN and never into healthy", () => {
    const state = build({ pipeline: { data: null, observedAt: null } });
    for (const id of ["radar", "luna", "dex", "echo", "byte", "nova"] as EmployeeId[]) {
      expect(state.employees[id].state, id).toBe("unknown");
    }
    expect(state.activity).toBe("UNKNOWN");
  });

  it("turns a failed pipeline request into UNKNOWN, and says so", () => {
    const state = build({ pipeline: { data: null, observedAt: null, failed: true } });
    expect(state.employees.radar.state).toBe("unknown");
    expect(state.employees.radar.detail).toContain("could not be read");
  });

  it("distinguishes never-asked from asked-and-failed", () => {
    const never = build({ pipeline: { data: null, observedAt: null } });
    expect(never.employees.radar.detail).toContain("has not been read yet");
  });

  it("turns a failed paper request into UNKNOWN for Milo and Rex", () => {
    const state = build({
      paperWallet: { data: null, observedAt: null, failed: true },
      paperPositions: { data: null, observedAt: null, failed: true },
    });
    expect(state.employees.milo.state).toBe("unknown");
    expect(state.employees.rex.state).toBe("unknown");
    expect(state.employees.milo.detail).toContain("could not be read");
  });

  it("turns a failed track-record request into UNKNOWN for Sage", () => {
    const state = build({ radarPerformance: { data: null, observedAt: null, failed: true } });
    expect(state.employees.sage.state).toBe("unknown");
  });

  it("never reports a healthy-looking state from an empty source", () => {
    // Exhaustive rather than representative: this is the property, and it has
    // to hold for whoever gets added next.
    const state = deriveHqState({ now: NOW });
    const healthy: EmployeeState[] = ["idle", "working", "busy", "success"];
    for (const employee of EMPLOYEES) {
      expect(healthy, employee.id).not.toContain(state.employees[employee.id].state);
    }
  });
});

describe("freshness", () => {
  it("lets a reading expire rather than staying green forever", () => {
    const stale = NOW - STALE_AFTER_MS.pipeline - 1;
    const state = build({ pipeline: at(pipeline(), stale) });
    expect(state.employees.radar.state).toBe("unknown");
    expect(state.employees.radar.detail).toContain("no longer describes now");
  });

  it("keeps a reading that is merely older than one poll", () => {
    const state = build({ pipeline: at(pipeline(), NOW - STALE_AFTER_MS.pipeline + 1_000) });
    expect(state.employees.radar.state).not.toBe("unknown");
  });

  it("expires paper and radar on their own windows", () => {
    const state = build({
      paperWallet: at(wallet(), NOW - STALE_AFTER_MS.paper - 1),
      paperPositions: at(positions(), NOW - STALE_AFTER_MS.paper - 1),
      radarPerformance: at(performance(), NOW - STALE_AFTER_MS.radar - 1),
    });
    expect(state.employees.milo.state).toBe("unknown");
    expect(state.employees.sage.state).toBe("unknown");
  });

  it("gates on all four ways a source can be untrustworthy", () => {
    expect(fresh({ data: null, observedAt: NOW }, 1000, NOW)).toBeNull();
    expect(fresh({ data: 1, observedAt: null }, 1000, NOW)).toBeNull();
    expect(fresh({ data: 1, observedAt: NOW, failed: true }, 1000, NOW)).toBeNull();
    expect(fresh({ data: 1, observedAt: NOW - 2000 }, 1000, NOW)).toBeNull();
    expect(fresh({ data: 1, observedAt: NOW }, 1000, NOW)).toBe(1);
  });
});

/* ── departments ─────────────────────────────────────────────────────── */

describe("Radar — discovery", () => {
  it("is idle when the scanner is healthy and quiet", () => {
    expect(build().employees.radar.state).toBe("idle");
  });

  it("works when the backend says a token landed in the last minute", () => {
    const state = build({ pipeline: at(pipeline({ scanner: { minutes_since_last_token: 0.3 } })) });
    expect(state.employees.radar.state).toBe("working");
  });

  it("reacts to discoveries on the stream", () => {
    const state = build({ activity: activity({ discovery: 3 }) });
    expect(state.employees.radar.state).toBe("working");
  });

  it("goes busy on high discovery throughput rather than per token", () => {
    const state = build({ activity: activity({ discovery: THRESHOLDS.busyDiscovery + 40 }) });
    expect(state.employees.radar.state).toBe("busy");
  });

  it("alerts when the scanner is degraded, and repeats the backend's reason", () => {
    const state = build({
      pipeline: at(pipeline({ scanner: { status: "degraded", failure_reason: "ws handshake failed" } })),
    });
    expect(state.employees.radar.state).toBe("alert");
    expect(state.employees.radar.detail).toBe("ws handshake failed");
  });

  it("goes offline when the scanner is down", () => {
    const state = build({ pipeline: at(pipeline({ scanner: { status: "down" } })) });
    expect(state.employees.radar.state).toBe("offline");
  });

  it("never reads busy from throughput while the scanner is degraded", () => {
    // Backend classification outranks event pressure. A degraded scanner that
    // happens to be emitting is still degraded.
    const state = build({
      pipeline: at(pipeline({ scanner: { status: "degraded" } })),
      activity: activity({ discovery: 200 }),
    });
    expect(state.employees.radar.state).toBe("alert");
  });
});

describe("Luna — analysis", () => {
  it("reviews rather than works when a backlog is queued but nothing scored", () => {
    const state = build({ pipeline: at(pipeline({ scoring: { pending: 4 } })) });
    expect(state.employees.luna.state).toBe("reviewing");
  });

  it("goes busy on a large scoring backlog", () => {
    const state = build({
      pipeline: at(pipeline({ scoring: { pending: THRESHOLDS.scoringBacklogBusy } })),
    });
    expect(state.employees.luna.state).toBe("busy");
  });

  it("alerts when scoring is degraded", () => {
    const state = build({ pipeline: at(pipeline({ scoring: { status: "degraded" } })) });
    expect(state.employees.luna.state).toBe("alert");
  });

  it("is idle when scoring is healthy and empty", () => {
    expect(build().employees.luna.state).toBe("idle");
  });
});

describe("Dex — market data", () => {
  it("alerts on stale tracked tokens even while the stage reports healthy", () => {
    // The load-bearing case. The backend classifies this stage purely on when
    // anything last landed and publishes the stale count without letting it
    // degrade the status — so a healthy stage can sit over hour-old prices.
    // A stale quote must never look healthy.
    const state = build({
      pipeline: at(
        pipeline({
          market: { status: "healthy", tracked_stale_count: 7, tracked_freshness_worst_seconds: 3600 },
        }),
      ),
    });
    expect(state.employees.dex.state).toBe("alert");
    expect(state.employees.dex.detail).toContain("7 tracked tokens");
  });

  it("works on ordinary market traffic", () => {
    expect(build({ activity: activity({ market: 5 }) }).employees.dex.state).toBe("working");
  });

  it("goes busy under heavy market traffic", () => {
    const state = build({ activity: activity({ market: THRESHOLDS.busyMarket + 1 }) });
    expect(state.employees.dex.state).toBe("busy");
  });

  it("goes offline when enrichment is down", () => {
    const state = build({ pipeline: at(pipeline({ market: { status: "down" } })) });
    expect(state.employees.dex.state).toBe("offline");
  });
});

describe("Atlas — the risk officer, sourced as of HQ-6", () => {
  it("reports real counts from the shared evaluator", () => {
    const atlas = build().employees.atlas;
    expect(atlas.sourced).toBe(true);
    expect(atlas.metrics.find((m) => m.label === "Reviewed (24h)")?.value).toBe("12");
    expect(atlas.metrics.find((m) => m.label === "Unknown")?.value).toBe("12");
  });

  it("is UNKNOWN — never idle — when nothing has ever been evaluated", () => {
    // The single most dangerous response in this feature. Zero failures and
    // zero rejections is byte-identical to a perfectly clean platform if you
    // only read the counts, so `source_state` has to be what decides.
    const atlas = build({
      tokenSecurity: at(
        security({
          evaluated_recently: 0,
          unknown_count: 0,
          total_evaluations: 0,
          last_evaluation_at: null,
          source_state: "no_evaluations",
        }),
      ),
    }).employees.atlas;
    expect(atlas.state).toBe("unknown");
    expect(atlas.detail.toLowerCase()).toContain("nothing has been checked");
  });

  it("is UNKNOWN when the evidence is older than its own validity window", () => {
    const atlas = build({
      tokenSecurity: at(security({ source_state: "stale" })),
    }).employees.atlas;
    expect(atlas.state).toBe("unknown");
  });

  it("is UNKNOWN — never green — when the endpoint fails", () => {
    const atlas = build({
      tokenSecurity: { data: null, observedAt: null, failed: true },
    }).employees.atlas;
    expect(atlas.state).toBe("unknown");
    for (const metric of atlas.metrics) expect(metric.value, metric.label).toBeNull();
  });

  it("is UNKNOWN when the summary has aged past the browser's window", () => {
    const atlas = build({
      tokenSecurity: at(security(), NOW - STALE_AFTER_MS.tokenSecurity - 1),
    }).employees.atlas;
    expect(atlas.state).toBe("unknown");
  });

  it("raises an alert only for a positively detected unsafe token", () => {
    const atlas = build({
      tokenSecurity: at(
        security({
          failed_count: 3,
          unknown_count: 9,
          failures_by_reason: { MINT_AUTHORITY_ACTIVE: 2, VENUE_UNSUPPORTED: 1 },
        }),
      ),
    }).employees.atlas;
    expect(atlas.state).toBe("alert");
    expect(atlas.detail).toContain("MINT_AUTHORITY_ACTIVE");
  });

  it("does NOT alert on UNKNOWN alone", () => {
    // Liquidity security is unverifiable for every venue this platform
    // trades. That is a written-down gap, not an incident, and an officer who
    // alerts on it every minute is one nobody reads.
    const atlas = build({
      tokenSecurity: at(security({ failed_count: 0, unknown_count: 25 })),
    }).employees.atlas;
    expect(atlas.state).not.toBe("alert");
  });

  it("is idle only when a healthy source genuinely has nothing to report", () => {
    const atlas = build({
      tokenSecurity: at(
        security({ evaluated_recently: 0, unknown_count: 0, source_state: "live" }),
      ),
    }).employees.atlas;
    expect(atlas.state).toBe("idle");
  });

  it("no longer depends on the Real Wallet being enabled", () => {
    // The HQ-5 defect: the only per-mint safety rows in the platform were
    // written by the Real Wallet's dry-run preview, so a disabled wallet made
    // the whole risk department invisible. Nothing in Atlas's derivation
    // reads a wallet or an execution mode any more.
    expect(build().employees.atlas.state).not.toBe("unknown");
  });
});

describe("Milo — the paper portfolio", () => {
  it("works while positions are open", () => {
    const state = build({ paperWallet: at(wallet({ open_positions: 3 })) });
    expect(state.employees.milo.state).toBe("working");
    expect(state.employees.milo.detail).toContain("3 open positions");
  });

  it("is idle with an empty portfolio", () => {
    expect(build().employees.milo.state).toBe("idle");
  });

  it("goes offline when the paper wallet is disabled, not idle", () => {
    const state = build({ paperWallet: at(wallet({}, false)) });
    expect(state.employees.milo.state).toBe("offline");
  });

  it("falls back to the positions list when the wallet has no count", () => {
    const state = build({
      paperWallet: { data: null, observedAt: null },
      paperPositions: at(positions(2)),
    });
    expect(state.employees.milo.state).toBe("working");
  });

  it("decides nothing about whether a position is stagnant", () => {
    // Holding-period judgement belongs to the strategy, which is being written
    // elsewhere. HQ reports that positions exist and stops there.
    const detail = build({ paperWallet: at(wallet({ open_positions: 5 })) }).employees.milo.detail;
    for (const word of ["stagnant", "stale", "should", "recommend", "exit"]) {
      expect(detail.toLowerCase()).not.toContain(word);
    }
  });
});

describe("Rex — paper execution only", () => {
  it("is idle without evidence of a fill", () => {
    expect(build().employees.rex.state).toBe("idle");
  });

  it("says on his own panel that the desk is simulated", () => {
    const desk = build().employees.rex.metrics.find((m) => m.label === "Desk");
    expect(desk?.value).toContain("simulated");
  });

  it("reacts to a close only when the permanent record actually grew", () => {
    const before = witness({ paperAudit: at(audit(4, "12.50")), paperWallet: at(wallet()) });
    const after = witness({ paperAudit: at(audit(5, "12.50")), paperWallet: at(wallet()) });

    expect(react(before, before, NOW).rex).toBeUndefined();
    expect(react(before, after, NOW).rex?.state).toBe("success");
  });

  it("reviews a losing close rather than dramatising it", () => {
    const before = witness({ paperAudit: at(audit(4, "-8.00")) });
    const after = witness({ paperAudit: at(audit(5, "-8.00")) });
    const reaction = react(before, after, NOW).rex;
    expect(reaction?.state).toBe("reviewing");
    expect(reaction?.detail).not.toMatch(/lost|fail|bad/i);
  });

  it("works when a position opens", () => {
    const before = witness({ paperWallet: at(wallet({ open_positions: 1 })), paperAudit: at(audit(2)) });
    const after = witness({ paperWallet: at(wallet({ open_positions: 2 })), paperAudit: at(audit(2)) });
    expect(react(before, after, NOW).rex?.state).toBe("working");
  });

  it("reacts to nothing on the first reading", () => {
    // No previous witness means no diff, and a diff against nothing would fire
    // a reaction for every trade ever made the moment the page opened.
    expect(react(null, witness({ paperAudit: at(audit(500, "1")) }), NOW)).toEqual({});
  });

  it("does not pretend to trade on a Real Wallet event", () => {
    // The distance between a simulated fill and a real one is the most
    // important thing this product communicates. Real Wallet is the Vault's
    // subject, not Rex's, and no path exists from those events to this desk.
    expect(kindOf("real_wallet.changed")).toBeNull();
    expect(kindOf("real_wallet.dry_run.changed")).toBeNull();

    const meter = createEventMeter(NOW - 120_000);
    for (let i = 0; i < 50; i += 1) meter.record("real_wallet.changed", NOW);
    const state = build({ activity: meter.snapshot(NOW) });
    expect(state.employees.rex.state).toBe("idle");
    expect(state.employees.milo.state).toBe("idle");
  });
});

describe("Echo — operations", () => {
  it("works through an ordinary queue", () => {
    const state = build({ pipeline: at(pipeline({ market: { queue_depth: 5 } })) });
    expect(state.employees.echo.state).toBe("working");
  });

  it("goes busy when a backlog has been waiting", () => {
    const state = build({
      pipeline: at(
        pipeline({
          market: {
            queue_depth: 40,
            oldest_normal_wait_seconds: THRESHOLDS.enrichmentWaitBusySeconds + 1,
          },
        }),
      ),
    });
    expect(state.employees.echo.state).toBe("busy");
  });

  it("alerts on a dead-letter problem", () => {
    const state = build({ pipeline: at(pipeline({ market: { dead_lettered: 3 } })) });
    expect(state.employees.echo.state).toBe("alert");
    expect(state.employees.echo.detail).toContain("dead-letter");
  });

  it("alerts when the priority lane misses the backend's own staleness limit", () => {
    const state = build({
      pipeline: at(
        pipeline({
          market: { oldest_priority_wait_seconds: THRESHOLDS.priorityWaitAlertSeconds + 5 },
        }),
      ),
    });
    expect(state.employees.echo.state).toBe("alert");
  });

  it("is idle on a clear queue", () => {
    expect(build().employees.echo.state).toBe("idle");
  });

  it("offers worker introspection as NOT AVAILABLE", () => {
    const worker = build().employees.echo.metrics.find((m) => m.label === "Worker pool");
    expect(worker?.value).toBeNull();
  });
});

describe("Byte — infrastructure", () => {
  it("is idle when the API answers and the stream is live", () => {
    expect(build().employees.byte.state).toBe("idle");
  });

  it("alerts on a lost event stream without claiming the backend is down", () => {
    const state = build({ stream: "reconnecting" });
    expect(state.employees.byte.state).toBe("alert");
    expect(state.employees.byte.detail).toContain("still answering");
  });

  it("does not treat a lost socket as a system outage anywhere else", () => {
    const state = build({ stream: "offline" });
    for (const id of ["radar", "luna", "dex", "echo", "milo"] as EmployeeId[]) {
      expect(state.employees[id].state, id).not.toBe("offline");
    }
    expect(state.activity).toBe("BUSY");
  });

  it("offers unpublished infrastructure figures as NOT AVAILABLE", () => {
    const byte = build().employees.byte;
    for (const label of ["Database latency", "Cache latency", "RPC health"]) {
      expect(byte.metrics.find((m) => m.label === label)?.value, label).toBeNull();
    }
  });
});

describe("Sage — the track record", () => {
  it("reports what the permanent record holds", () => {
    expect(build().employees.sage.state).toBe("idle");
    expect(build().employees.sage.detail).toContain("120 opportunities");
  });

  it("works briefly when the record changes", () => {
    const before = witness({ radarPerformance: at(performance(120)) });
    const after = witness({ radarPerformance: at(performance(121)) });
    expect(react(before, after, NOW).sage?.state).toBe("working");
  });
});

/* ── the roll-up ─────────────────────────────────────────────────────── */

describe("Nova — the roll-up", () => {
  it("reads the office rather than the API", () => {
    const state = build({ pipeline: at(pipeline({ scanner: { status: "down" } })) });
    expect(state.employees.nova.state).toBe("reviewing");
    expect(state.employees.nova.detail).toContain("One department");
  });

  it("alerts once several departments are reporting faults", () => {
    const state = build({
      pipeline: at(
        pipeline({
          scanner: { status: "down" },
          scoring: { status: "degraded" },
          market: { dead_lettered: 2 },
        }),
      ),
    });
    expect(state.employees.nova.state).toBe("alert");
  });

  it("is never healthy while a sourced department has no reading", () => {
    const state = build({ paperWallet: { data: null, observedAt: null, failed: true } });
    expect(["idle", "success"]).not.toContain(state.employees.nova.state);
    expect(state.employees.nova.state).toBe("reviewing");
  });

  it("is UNKNOWN when the critical source is unavailable", () => {
    const state = build({ pipeline: { data: null, observedAt: null, failed: true } });
    expect(state.employees.nova.state).toBe("unknown");
  });

  it("does not react dramatically to ordinary busy departments", () => {
    const state = build({ activity: activity({ market: 200, discovery: 60 }) });
    expect(state.employees.nova.state).toBe("working");
  });
});

describe("office activity", () => {
  it("is QUIET when everything reporting is quiet", () => {
    // Atlas is a working department since HQ-6, so a quiet office means his
    // source is live and has genuinely nothing new — not that it is missing.
    const quietAtlas = at(
      security({ evaluated_recently: 0, unknown_count: 0, source_state: "live" }),
    );
    expect(build({ tokenSecurity: quietAtlas }).activity).toBe("QUIET");
  });

  it("is NORMAL on ordinary traffic", () => {
    expect(build({ activity: activity({ market: 3 }) }).activity).toBe("NORMAL");
  });

  it("is BUSY when several departments are busy", () => {
    const state = build({
      activity: activity({ market: 200, discovery: 60, score: 60 }),
    });
    expect(state.activity).toBe("BUSY");
  });

  it("is HIGH_ALERT on a serious incident", () => {
    const state = build({ pipeline: at(pipeline({ market: { status: "down" } })) });
    expect(state.activity).toBe("HIGH_ALERT");
  });

  it("is UNKNOWN when the critical source is missing", () => {
    expect(build({ pipeline: { data: null, observedAt: null } }).activity).toBe("UNKNOWN");
  });

  it("is never driven by a price alone", () => {
    // Market movement is not an incident. A hundred price ticks make a busy
    // market desk, and nothing more than that.
    expect(build({ activity: activity({ market: 240 }) }).activity).not.toBe("HIGH_ALERT");
  });
});

/* ── priority ────────────────────────────────────────────────────────── */

describe("state priority", () => {
  it("lists everyone doing real work as operational", () => {
    const state = build({
      pipeline: at(pipeline({ scanner: { minutes_since_last_token: 0.2 }, market: { queue_depth: 3 } })),
    });
    expect(state.operational).toContain("radar");
    expect(state.operational).toContain("echo");
    // Atlas belongs here now: he has a source and it is reporting work.
    expect(state.operational).toContain("atlas");
  });

  it("leaves idle and unknown staff free for ambient personality", () => {
    // Ambient is the bottom layer, but it is not a punishment: someone with
    // nothing operational to say should still look alive.
    const state = build({
      tokenSecurity: at(
        security({ evaluated_recently: 0, unknown_count: 0, source_state: "live" }),
      ),
    });
    expect(state.operational).not.toContain("atlas");
    expect(state.operational).not.toContain("luna");
  });

  it("never lets a reaction paint over a real problem", () => {
    const state = build({
      pipeline: at(pipeline({ market: { status: "down" } })),
      transients: { dex: { state: "success", detail: "nonsense", until: NOW + 5_000 } },
    });
    expect(state.employees.dex.state).toBe("offline");
  });

  it("drops a reaction once it has expired", () => {
    const state = build({
      transients: { rex: { state: "success", detail: "closed in profit", until: NOW - 1 } },
    });
    expect(state.employees.rex.state).toBe("idle");
  });

  it("applies a live reaction over an ordinary state", () => {
    const state = build({
      transients: { rex: { state: "success", detail: "closed in profit", until: NOW + 5_000 } },
    });
    expect(state.employees.rex.state).toBe("success");
    expect(state.employees.rex.detail).toBe("closed in profit");
  });

  it("never applies a reaction to an unsourced department", () => {
    // Atlas with a failed endpoint is the unsourced case now. A transient must
    // not be able to paint him as busy when nothing answered.
    const state = build({
      tokenSecurity: { data: null, observedAt: null, failed: true },
      transients: { atlas: { state: "reviewing", detail: "invented", until: NOW + 5_000 } },
    });
    expect(state.employees.atlas.state).toBe("unknown");
  });

  it("counts exactly the states that should interrupt ambient personality", () => {
    expect([...OPERATIONAL_STATES].sort()).toEqual(
      ["alert", "busy", "error", "offline", "reviewing", "success", "working"].sort(),
    );
    expect(OPERATIONAL_STATES.has("idle")).toBe(false);
    expect(OPERATIONAL_STATES.has("unknown")).toBe(false);
  });
});

/* ── panels ──────────────────────────────────────────────────────────── */

describe("panels", () => {
  it("gives every metric a source", () => {
    const state = build();
    for (const employee of EMPLOYEES) {
      for (const metric of state.employees[employee.id].metrics) {
        expect(metric.source, `${employee.id}/${metric.label}`).toBeTruthy();
      }
    }
  });

  it("renders every figure as null rather than zero when the source is gone", () => {
    const state = deriveHqState({ now: NOW });
    for (const employee of EMPLOYEES) {
      for (const metric of state.employees[employee.id].metrics) {
        // Two exceptions, and both are facts the browser holds on its own
        // rather than readings from a backend: Rex's fixed desk label, and the
        // state of this tab's own WebSocket. Neither can be unavailable
        // because neither was ever fetched.
        if (metric.source === "HQ" || metric.source === "browser WebSocket") continue;
        expect(metric.value, `${employee.id}/${metric.label}`).toBeNull();
      }
    }
  });

  it("gives every employee a sentence explaining their state", () => {
    const state = build();
    for (const employee of EMPLOYEES) {
      expect(state.employees[employee.id].detail.length, employee.id).toBeGreaterThan(10);
    }
  });
});

describe("the entry security gate survives a generation cutover", () => {
  /**
   * This was a single id compared with `===`, and the HOLD-6H cutover made it
   * stale on the day it landed: the backend gate was strict and enforcing, and
   * the Portfolio board read NOT ENFORCED because the successor's id was not
   * the one string it knew. A board that reports a live security gate as off
   * is a false claim about safety, which is the one thing HQ may never make.
   */
  it("recognises every gated generation, not just the newest", () => {
    expect(isSecurityGated("trailing_stop_25_secured_hold6h_v3")).toBe(true);
    expect(isSecurityGated("trailing_stop_25_secured_v2")).toBe(true);
  });

  it("still reports an ungated strategy as ungated", () => {
    expect(isSecurityGated("trailing_stop_25_v1")).toBe(false);
    expect(isSecurityGated("equal_weight_v1")).toBe(false);
  });

  it("says nothing when the backend has not said anything", () => {
    expect(isSecurityGated(null)).toBe(false);
    expect(isSecurityGated(undefined)).toBe(false);
  });
});
