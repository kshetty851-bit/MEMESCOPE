import { api } from "@/lib/api-client";

import * as mock from "./mock";
import type {
  BreakoutRow,
  EpisodePage,
  Health,
  NearRow,
  Source,
  Stats,
  StockView,
} from "./types";

/**
 * NSE TRACKER CLIENT
 *
 * Fetches and nothing else. **It never decides.** Every figure — the score,
 * the distance to resistance, the return, the decile bucket — arrives already
 * computed. A threshold applied here would be a second, unpublished rule
 * competing with the one the tracker actually followed, and the two would
 * disagree the first time either changed.
 *
 * There is no write. The backend router has no POST, PUT, PATCH or DELETE and
 * a test on that side asserts it.
 *
 * MOCK MODE. `NEXT_PUBLIC_NSE_TRACKER_MOCK=true` serves `mock.ts` instead of
 * the network, for developing against an empty database. The variable is
 * referenced by its full literal name because Next inlines `NEXT_PUBLIC_*` at
 * build time and would not replace a destructured read. It is deliberately NOT
 * added to `src/lib/env.ts`: that file is shared, and this lab edits nothing
 * outside its own folder beyond one nav entry and one route.
 */
export const MOCK = process.env.NEXT_PUBLIC_NSE_TRACKER_MOCK === "true";

const mocked = <T>(value: T): Promise<T> => Promise.resolve(value);

export const fetchHealth = () =>
  MOCK ? mocked(mock.MOCK_HEALTH) : api.get<Health>("/tracker/health");

export const fetchNear = (limit = 200) =>
  MOCK ? mocked(mock.MOCK_NEAR) : api.get<NearRow[]>(`/tracker/near?limit=${limit}`);

export const fetchBreakouts = (days = 30, source: Source = "live") =>
  MOCK
    ? mocked(mock.MOCK_BREAKOUTS)
    : api.get<BreakoutRow[]>(`/tracker/breakouts?days=${days}&source=${source}`);

export const fetchStock = (symbol: string, candles = 750) =>
  MOCK
    ? mocked(mock.MOCK_STOCK)
    : api.get<StockView>(
        `/tracker/stock/${encodeURIComponent(symbol)}?candles=${candles}`);

export const fetchEpisodes = (source: Source = "replay", limit = 25, offset = 0) =>
  MOCK
    ? mocked(mock.MOCK_EPISODES)
    : api.get<EpisodePage>(
        `/tracker/episodes?source=${source}&limit=${limit}&offset=${offset}`);

export const fetchStats = (source: Source = "replay") =>
  MOCK
    ? mocked(source === "live" ? mock.MOCK_STATS_LIVE : mock.MOCK_STATS)
    : api.get<Stats>(`/tracker/stats?source=${source}`);
