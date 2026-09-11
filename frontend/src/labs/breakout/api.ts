import { api } from "@/lib/api-client";

import * as mock from "./mock";
import type {
  Account,
  BreakoutHealth,
  EpisodePage,
  EquityPoint,
  Position,
  Setup,
  SetupDetail,
  SetupStats,
  TradePage,
  TradeStats,
} from "./types";

/**
 * BREAKOUT LAB CLIENT
 *
 * Fetches and nothing else. **It never decides.** Every figure — the score,
 * the distance to resistance, the trailing-stop level, the drawdown — arrives
 * already computed. A threshold applied here would be a second, unpublished
 * rule competing with the one the lab actually followed, and the two would
 * disagree the first time either changed.
 *
 * There is no write. The lab trades on its own tick: no manual entry, no
 * manual exit, no activation endpoint. The backend router has no such route
 * either, and a test on that side asserts it.
 *
 * MOCK MODE. `NEXT_PUBLIC_BREAKOUT_MOCK=true` serves `mock.ts` instead of the
 * network, for developing the page against an empty database. The variable is
 * referenced by its full literal name because Next inlines `NEXT_PUBLIC_*` at
 * build time and would not replace a destructured read. It is deliberately
 * NOT added to `src/lib/env.ts`: that file is shared, and this lab may not
 * edit anything outside its own folder beyond one nav entry and one route.
 */
export const MOCK = process.env.NEXT_PUBLIC_BREAKOUT_MOCK === "true";

const mocked = <T>(value: T): Promise<T> => Promise.resolve(value);

export const fetchHealth = () =>
  MOCK ? mocked(mock.MOCK_HEALTH) : api.get<BreakoutHealth>("/labs/breakout/health");

export const fetchSetups = () =>
  MOCK ? mocked(mock.MOCK_SETUPS) : api.get<Setup[]>("/labs/breakout/setups");

export const fetchSetupDetail = (mint: string) =>
  MOCK
    ? mocked(mock.MOCK_DETAIL)
    : api.get<SetupDetail>(`/labs/breakout/setups/${mint}`);

export const fetchEpisodes = (limit = 25, offset = 0) =>
  MOCK
    ? mocked(mock.MOCK_EPISODES)
    : api.get<EpisodePage>(`/labs/breakout/episodes?limit=${limit}&offset=${offset}`);

export const fetchStats = () =>
  MOCK ? mocked(mock.MOCK_STATS) : api.get<SetupStats>("/labs/breakout/stats");

export const fetchAccount = () =>
  MOCK ? mocked(mock.MOCK_ACCOUNT) : api.get<Account>("/labs/breakout/account");

export const fetchPositions = () =>
  MOCK ? mocked(mock.MOCK_POSITIONS) : api.get<Position[]>("/labs/breakout/positions");

export const fetchTrades = (limit = 25, offset = 0) =>
  MOCK
    ? mocked(mock.MOCK_TRADES)
    : api.get<TradePage>(`/labs/breakout/trades?limit=${limit}&offset=${offset}`);

export const fetchEquity = (hours = 168) =>
  MOCK
    ? mocked(mock.MOCK_EQUITY)
    : api.get<EquityPoint[]>(`/labs/breakout/equity?hours=${hours}`);

export const fetchTradeStats = () =>
  MOCK ? mocked(mock.MOCK_TRADE_STATS) : api.get<TradeStats>("/labs/breakout/trade_stats");

/** Server codes, rendered here, never composed. */
export const EXIT_LABELS: Record<string, string> = {
  trail_stop: "Trailing stop",
  failed_setup: "Setup failed",
  time_stop: "Time stop",
  forced_exit: "Forced exit",
  halt: "Kill switch",
  flatten: "Flattened",
};

export const CLOSE_REASON_LABELS: Record<string, string> = {
  BROKE_OUT: "Broke out",
  FAILED: "Failed",
  EXPIRED: "Expired",
  universe_exit: "Left universe",
};
