import { api } from "@/lib/api-client";

import type { BacktestIn, BacktestOut, ConfigOut, StatusOut } from "./types";

/**
 * BTC RANGE LAB CLIENT
 *
 * Paper only. The one POST is a backtest: it replays stored candles through
 * the strategy and returns a result. It places no order and writes nothing the
 * live book can see.
 */
export function fetchStatus(): Promise<StatusOut> {
  return api.get<StatusOut>("/labs/btc-range/status");
}

export function fetchConfig(): Promise<ConfigOut> {
  return api.get<ConfigOut>("/labs/btc-range/config");
}

export function runBacktest(body: BacktestIn): Promise<BacktestOut> {
  return api.post<BacktestOut>("/labs/btc-range/backtest", body);
}
