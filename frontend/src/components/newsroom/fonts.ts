import { Big_Shoulders, Geist_Mono, Source_Serif_4, UnifrakturMaguntia } from "next/font/google";

/** Nameplate: a blackletter newspaper flag. */
export const nameplate = UnifrakturMaguntia({ subsets: ["latin"], weight: "400", variable: "--np-flag", display: "swap" });
/** Headlines: a condensed grotesque cut for tabloid-scale heads. */
export const headline = Big_Shoulders({ subsets: ["latin"], weight: ["600", "800", "900"], variable: "--np-head", display: "swap" });
/** Reading text. */
export const body = Source_Serif_4({ subsets: ["latin"], weight: ["400", "600"], style: ["normal", "italic"], variable: "--np-body", display: "swap" });
/** Prices, times, counts: figures only. */
export const figures = Geist_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--np-mono", display: "swap" });
