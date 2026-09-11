/** Shapes returned by `/labs/graduation/status`. Mirrors `api.py`. */

export interface Funnel {
  seen: number;
  crossed_70: number;
  crossed_80: number;
  crossed_90: number;
  crossed_95: number;
  graduated: number;
}

/**
 * Graduation is reported by two INDEPENDENT sources and either can arrive
 * alone, so the split is published rather than summed away.
 */
export interface Signals {
  both: number;
  feed_only: number;
  chain_only: number;
}

export interface RecentToken {
  mint: string;
  symbol: string | null;
  max_progress_pct: string | null;
  tracked: boolean;
  migrated: boolean;
  sample_count: number;
}

export interface GraduationStatus {
  running: boolean;
  rpc_host: string;
  poll_interval_s: number;
  watch_set: number;
  watch_set_max: number;
  funnel: Funnel;
  signals: Signals;
  curve_samples: number;
  checkpoints: number;
  checkpoints_with_reserves: number;
  postgrad_samples: number;
  rpc_calls_per_minute: number;
  samples_last_hour: number;
  tokens_last_hour: number;
  recent: RecentToken[];
  quote_side_trusted: boolean;
}
