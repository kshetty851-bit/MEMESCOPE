/** The newsroom bundle, exactly as `GET /api/v1/newsroom` serves it (app/newsroom). */
export type Kind = "confirmed" | "report" | "developing" | "commentary";

export interface TimelineItem { source: string; title: string; url: string; at: string }

export interface Story {
  id: string; title: string; summary: string; url: string; source: string; image: string | null;
  first_at: string; last_at: string; sources: number; publishers: string[];
  topics: string[]; regions: string[]; kind: Kind; timeline: TimelineItem[];
}

export interface Coin {
  id: string; symbol: string; name: string; image: string | null; price: number | null;
  mcap: number | null; volume: number | null; ch1h: number | null; ch24h: number | null;
  ch7d: number | null; spark: number[];
}

export interface Market {
  total_mcap: number | null; top100_volume: number | null; mcap_change_24h: number | null;
  btc_dominance: number | null; eth_dominance: number | null; active_coins: number | null; coins: Coin[];
}

export interface Narrative { id: string; name: string; mcap: number; change_24h: number; volume: number | null }
export interface Hack { name: string; date: string; amount_usd: number | null; chains: string[]; technique: string | null; source: string | null }
export interface BtcNet {
  height: number; difficulty_change_pct: number; difficulty_at: string; difficulty_blocks_left: number;
  halving_height: number; halving_blocks_left: number; halving_estimate: string;
}
export interface Ours {
  graduations_24h: number; graduations_1h: number; rug_measured_24h: number; rugged_24h: number;
  rug_rate_24h: number | null; recent_drains: { mint: string; symbol: string | null; name: string | null; graduated_at: string }[];
  /** Graduated in the last day and not drained in hour one, best first hour first (2026-10-20). */
  survivors?: { mint: string; symbol: string | null; name: string | null; graduated_at: string; liquidity_usd: number; change_1h_pct: number | null }[];
  /** Graduations in each of the last 24 clock hours, oldest first (2026-10-20). */
  hourly?: { hour: string; graduations: number }[];
  karthik_lab: { started_at: string; judge_at: string; balance_usd: string; pnl_usd: string; pnl_pct: string; capital_usd: string; trades: number; wins: number; rugs: number } | null;
}
export interface MapPoint { code: string; name: string; lat: number; lon: number; count: number; stories: { id: string; title: string; url: string; source: string; at: string }[] }
export interface SourceStatus { kind: "news" | "data"; ok: boolean; last_ok?: string; error?: string | null; items?: number }

export interface Newsroom {
  warming_up?: boolean;
  server_time: string;
  generated_at?: string;
  status?: Record<string, SourceStatus>;
  market?: Market | null;
  narratives?: Narrative[] | null;
  fear_greed?: { value: number; label: string; yesterday: number | null } | null;
  hacks?: Hack[] | null;
  bitcoin_network?: BtcNet | null;
  ours?: Ours | null;
  stories?: Story[];
  lead?: Story | null;
  map?: MapPoint[];
  briefing?: { what: string[]; why: string[]; watch: string[]; note: string };
  unavailable?: { section: string; why: string }[];
}

export const TOPIC_LABEL: Record<string, string> = {
  bitcoin: "Bitcoin", ethereum: "Ethereum", defi: "DeFi", exchanges: "Exchanges", regulation: "Regulation",
  adoption: "Adoption", nfts: "NFTs", gaming: "Gaming", security: "Security", memecoins: "Memecoins",
  stablecoins: "Stablecoins", solana: "Solana", macro: "Macro",
};
