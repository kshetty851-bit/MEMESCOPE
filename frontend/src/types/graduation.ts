/** What happens in the hour after a pump.fun coin graduates. */

export interface GraduationAge {
  minutes: number;
  n: number;
  median_pct?: number;
  mean_pct?: number;
  pct_up?: number;
  worst_pct?: number;
  best_pct?: number;
}

export interface GraduationCohort {
  disclosure: string;
  cohort: number;
  total_stamped: number;
  /** Coins already graduated when the collector first looked. Their stamp is
   *  when we started watching, not when they graduated, so they are excluded. */
  excluded_cold_start: number;
  since: string | null;
  ages: GraduationAge[];
}
