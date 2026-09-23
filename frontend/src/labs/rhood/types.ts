/** What `/labs/rhood/status` returns. A recorder's window, not a board. */
export interface RhoodEvent {
  symbol: string | null;
  name: string | null;
  token: string;
  pool: string | null;
  at: string;
  pairs_seen: number | null;
  priced: boolean;
  /** One pair and no older listing: a coin meeting the market for the first
      time, rather than an extra pool on one that already trades. */
  is_launch: boolean;
}

export interface RhoodStatus {
  enabled: boolean;
  chain_id: number;
  factory: string;
  watching_since: string | null;
  samples: number;
  events_total: number;
  events_24h: number;
  launches_24h: number;
  launches_1h: number;
  unpriced_24h: number;
  recent: RhoodEvent[];
}
