import { api } from "@/lib/api-client";

import type {
  MomentumBoard,
  MomentumSignals,
  MomentumStatus,
  MomentumTrades,
} from "./types";

/** MOMENTUM LAB CLIENT. Fetches only: the backend router has no write route. */
export function fetchStatus(): Promise<MomentumStatus> {
  return api.get<MomentumStatus>("/labs/momentum/status");
}

export function fetchBoard(): Promise<MomentumBoard> {
  return api.get<MomentumBoard>("/labs/momentum/board");
}

export function fetchTrades(arm: string): Promise<MomentumTrades> {
  return api.get<MomentumTrades>(`/labs/momentum/trades?arm=${encodeURIComponent(arm)}`);
}

export function fetchSignals(): Promise<MomentumSignals> {
  return api.get<MomentumSignals>("/labs/momentum/signals?limit=40");
}
