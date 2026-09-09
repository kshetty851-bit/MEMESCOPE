import { api } from "@/lib/api-client";

import type { KolBoard, KolWallets } from "@/types/kol";
import type { LabTrades } from "@/types/lab";

/** The signal wallet and its control, side by side. */
export function fetchKolBoard(): Promise<KolBoard> {
  return api.get<KolBoard>("/kol/board");
}

/** The frozen ranking, with the base rate it has to beat. */
export function fetchKolWallets(): Promise<KolWallets> {
  return api.get<KolWallets>("/kol/wallets");
}

export function fetchKolTrades(): Promise<LabTrades> {
  return api.get<LabTrades>("/kol/trades?limit=2000");
}
