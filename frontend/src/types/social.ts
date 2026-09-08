/**
 * The Social pair: one signal, one control, one condition apart.
 *
 * Deliberately NOT a leaderboard type — there is no floor, no ladder and no
 * ranking worth reading here. Two wallets that differ in whether they require
 * a coin's comment rate to be rising, and the comparison between them is the
 * entire result.
 */

import type { LabBoard, LabCell, LabTrade } from "@/types/lab-cell";

export type SocialTrade = LabTrade;

export interface SocialCell extends LabCell {
  /** Which arm this is. The control is half the experiment, not a footnote. */
  is_control: boolean;
}

export type SocialBoard = LabBoard<SocialCell>;
