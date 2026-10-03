import type {
  LifecycleOverview,
  MemeDetail,
  MemeList,
  Measured,
  SourceHealth,
} from "./types";

/** Test fixtures shaped exactly like the contract in docs/MEME_LIFECYCLE_LAB.md. */

export const m = (value: string | null, reason: string | null = null): Measured => ({
  value,
  unavailable_reason: value === null ? (reason ?? "no_source") : null,
});

export const SOURCES: SourceHealth[] = [
  { source: "gdelt", label: "GDELT (news)", status: "available", reason: null,
    last_run_at: "2026-10-03T12:00:00Z", data_class: "forward", observations_24h: 96 },
  { source: "reddit", label: "Reddit", status: "disabled", reason: "disabled_by_config",
    last_run_at: null, data_class: "forward", observations_24h: null },
  { source: "x", label: "X", status: "disabled", reason: "disabled_by_config",
    last_run_at: null, data_class: "forward", observations_24h: null },
  { source: "geckoterminal", label: "GeckoTerminal (OHLCV)", status: "available", reason: null,
    last_run_at: "2026-10-02T01:00:00Z", data_class: "backfill", observations_24h: 0 },
];

export const OVERVIEW: LifecycleOverview = {
  lab_enabled: true,
  real_trading: false,
  mode: "authoritative",
  forward_start: "2026-10-01T00:00:00Z",
  forward_days: 2.5,
  portfolio: {
    run_id: null, as_of: null, starting_capital: "1000",
    equity: null, cash: null, deployed: null, realized_pnl: null, unrealized_pnl: null,
    roi: null, drawdown: null, trades: 0, open_positions: 0,
    sample_label: "insufficient (<25)", unavailable_reason: "no_forward_run_yet",
  },
  experiment: {
    experiment_key: "baseline-v1", split_meaningful: false,
    split_note: "Not enough forward data for a chronological 70/15/15 split.",
    train: ["2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"],
    validation: ["2026-10-02T00:00:00Z", "2026-10-02T12:00:00Z"],
    test: ["2026-10-02T12:00:00Z", "2026-10-03T00:00:00Z"],
  },
  sources: SOURCES,
  tracked_memes: 3,
  linked_tokens: 4,
  notes: ["Only forward data collected since 2026-10-01 counts toward the verdict."],
};

export const MEMES: MemeList = {
  generated_at: "2026-10-03T12:00:00Z",
  items: [
    {
      slug: "frogceo", display_name: "FROGCEO",
      tokens: [{ mint: "FrogMint1111111111111111111111111111111pump", symbol: "FROGCEO",
        name: "Frog CEO", link_method: "manual", confidence: "0.8", linked_at: "2026-10-02T00:00:00Z" }],
      primary_mint: "FrogMint1111111111111111111111111111111pump",
      token_age_seconds: 345600, age_bucket: "3-7d",
      market_cap: "125000", liquidity_usd: null, volume_1h: "8200", price_change_1h: "0.12",
      attention: {
        mentions_1h: m("14"), mentions_24h: m("220"),
        velocity: m(null, "no_source"), acceleration: m(null, "insufficient_history"),
        baseline_multiple: m("4.7"), platform_count: m("2"),
      },
      lifecycle_state: "reviving", market_activity: m("0.35"),
      data_freshness_seconds: 120, paper_status: "none", contains_backfill: false,
    },
  ],
};

const day = (d: number, h = 0) =>
  `2026-10-${String(d).padStart(2, "0")}T${String(h).padStart(2, "0")}:00:00Z`;

export const DETAIL: MemeDetail = {
  meme: { slug: "frogceo", display_name: "FROGCEO", description: "A frog in a suit.",
    tracking_started_at: day(1), wikipedia_title: null, gdelt_query: "frog ceo" },
  aliases: [{ alias: "Frog CEO", kind: "name", added_at: day(1) }],
  links: [{ mint: "FrogMint1111111111111111111111111111111pump", method: "manual",
    confidence: "0.8", linked_at: day(2, 6), unlinked_at: null }],
  series: {
    attention: [
      { t: day(1, 0), value: "2" }, { t: day(1, 1), value: "5" },
      { t: day(1, 2), value: null }, { t: day(1, 3), value: "9" },
      { t: day(1, 4), value: "12" },
    ],
    price: [
      { t: day(1, 0), value: "0.001" }, { t: day(1, 1), value: "0.002" },
      { t: day(1, 2), value: "0.0015" }, { t: day(1, 3), value: null },
      { t: day(1, 4), value: "0.004" },
    ],
    volume: [
      { t: day(1, 0), value: "100" }, { t: day(1, 1), value: "400" },
      { t: day(1, 2), value: "300" }, { t: day(1, 3), value: "900" },
      { t: day(1, 4), value: "700" },
    ],
    per_source: {
      gdelt: [{ t: day(1, 0), value: "1" }, { t: day(1, 1), value: null }, { t: day(1, 2), value: "3" }],
      reddit: [],
    },
    backfill_before: day(1, 2),
  },
  markers: [
    { t: day(1, 0), kind: "token_launch", label: "Token launched", event_type: null, mint: null },
    { t: day(1, 1), kind: "attention_spike", label: "Attention spike", event_type: "attention_spike", mint: null },
    { t: day(1, 3), kind: "paper_entry", label: "Paper entry", event_type: null, mint: "FrogMint1111111111111111111111111111111pump" },
  ],
  events: [{
    event_type: "attention_spike", detected_at: day(1, 1), mint: "FrogMint1111111111111111111111111111111pump",
    divergence_case: "attention_leads_market", lifecycle_state: "emerging", mode: "exploratory",
    contains_backfill: true,
    returns: { "5m": m("0.02"), "15m": m("0.05"), "1h": m(null, "horizon_not_elapsed"), "24h": m(null, "horizon_not_elapsed") },
    price_at_detection: "0.002", run_up_before_detection: m("0.4"),
  }],
  trades: [{
    trade_key: "t1", mint: "FrogMint1111111111111111111111111111111pump",
    entry_at: day(1, 3), entry_price: "0.0015", size_usd: "10", exit_at: null, exit_price: null,
    exit_reason: null, pnl_usd: null, return_pct: null, status: "open",
    entry_reason: "attention_with_market_confirmation",
    evidence_timeline: [{ at: day(1, 3), kind: "attention_spike", detail: "Mentions rose to 4.7x baseline" }],
  }],
  data_label: "exploratory", contains_backfill: true, sources: SOURCES,
};
