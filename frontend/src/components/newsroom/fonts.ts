import { Bodoni_Moda, Courier_Prime, News_Cycle, Old_Standard_TT, UnifrakturMaguntia } from "next/font/google";

/** Nameplate: a blackletter newspaper flag. */
export const nameplate = UnifrakturMaguntia({ subsets: ["latin"], weight: "400", variable: "--np-flag", display: "swap" });
/** Headlines: a hairline-contrast Didone, the face of the old front page (2026-10-29, morning edition). */
export const headline = Bodoni_Moda({ subsets: ["latin"], weight: ["600", "800", "900"], style: ["normal", "italic"], variable: "--np-head", display: "swap" });
/** Tags, tabs, tickers: a News Gothic revival, the press room's label face. */
export const label = News_Cycle({ subsets: ["latin"], weight: ["400", "700"], variable: "--np-label", display: "swap" });
/** Reading text: a 19th-century news roman. */
export const body = Old_Standard_TT({ subsets: ["latin"], weight: ["400", "700"], style: ["normal", "italic"], variable: "--np-body", display: "swap" });
/** Prices, times, counts: typewriter figures only. */
export const figures = Courier_Prime({ subsets: ["latin"], weight: ["400", "700"], variable: "--np-mono", display: "swap" });
