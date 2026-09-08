/** The depth curve: twenty wallets differing only in their liquidity floor. */

import type { LabBoard, LabCell, LabTrade } from "@/types/lab-cell";

export type DepthTrade = LabTrade;

export interface DepthCell extends LabCell {
  /** The x-axis. Without it there is no curve. */
  floor_usd: number;
}

export type DepthBoard = LabBoard<DepthCell>;
