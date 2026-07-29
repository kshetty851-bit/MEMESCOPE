/**
 * Today's Opportunities — the sections the home page is built from.
 *
 * ## The constraint that shaped every rule below
 *
 * A section is a claim: putting a token under "Building Momentum" asserts
 * something about it. So each section is defined by a **flag the backend
 * already set** — a Radar category, a reason code the engine emitted, an Exit
 * Watch severity, a veto — never by this file reading a number and deciding
 * what it means.
 *
 * The one thing this module does with numbers is compare two figures the
 * backend produced (current multiple against peak multiple) to say a token is
 * below its own high. That is arithmetic on server-supplied values, not a
 * threshold: no constant is invoked and no band is invented.
 *
 * ## Where the brief and the data disagree
 *
 * "Early Accumulation" normally means wallets quietly building a position, and
 * MEMESCOPE cannot see wallets at all. Rather than approximate it from price —
 * which would be exactly the invented intelligence this codebase deletes on
 * sight — the section maps to the Radar's own `undervalued` category and its
 * description says plainly what it is measuring instead.
 *
 * Likewise "Recovery Candidates" is populated by a fact (trading below its
 * observed peak) and its copy refuses the implication that a recovery is
 * expected. The platform has no view on that.
 */

import type { RadarEntry } from "@/types/radar";
import type { TopScoreEntry } from "@/types/score";

export interface SectionDefinition {
  id: string;
  title: string;
  /** Shown under the heading. Says what the section is really measuring. */
  description: string;
  /** Answer to "why is this here?", shown behind the Why affordance. */
  basis: string;
}

export const SECTIONS: SectionDefinition[] = [
  {
    id: "highest_conviction",
    title: "Highest conviction today",
    description: "Where the signals the engine can read are most strongly aligned.",
    basis:
      "These sit in the engine's top bands. Four of nine signals have no data " +
      "source, so even the strongest token here carries limited confidence — " +
      "the band describes agreement among what could be read, not certainty.",
  },
  {
    id: "building_momentum",
    title: "Building momentum",
    description: "Improving against their own baseline, with volume behind the move.",
    basis:
      "Classified by the Radar as early momentum or breakout. Both are the " +
      "Radar's own categories, published at /api/v1/radar/categories.",
  },
  {
    id: "increasing_liquidity",
    title: "Increasing liquidity",
    description: "More capital is available to trade against than there was.",
    basis:
      "The Radar emitted its liquidity-growing reason for these tokens. " +
      "Liquidity is the signal most often missing entirely on bonding-curve " +
      "pools, so a token absent here may simply be unmeasured.",
  },
  {
    id: "early_accumulation",
    title: "Early accumulation",
    description:
      "Structure looks sound while the market has not moved. Measured from " +
      "on-chain structure, not from wallet behaviour.",
    basis:
      "The Radar's undervalued category. True accumulation would need holder " +
      "and wallet history, which MEMESCOPE does not collect — so this is a " +
      "structural reading, and the section is named for what it can actually see.",
  },
  {
    id: "recovery",
    title: "Recovery candidates",
    description:
      "Detected earlier and now trading below their observed peak. Listed " +
      "because a baseline already exists for them, not because a recovery is expected.",
    basis:
      "Current multiple is below peak multiple, both measured from MEMESCOPE's " +
      "first detection. The platform has no view on whether any of them recover.",
  },
  {
    id: "losing_strength",
    title: "Losing strength",
    description: "Exit Watch is reporting observable deterioration.",
    basis:
      "Exit Watch is a warning system and never a sell signal. It knows nothing " +
      "about anyone's position, cost basis or intent, and its thresholds are " +
      "deliberately lagging so it is right rather than early.",
  },
  {
    id: "highest_risk",
    title: "Highest risk",
    description: "Vetoed by the risk gate, or flagged at the highest Exit Watch severity.",
    basis:
      "A veto caps the score outright regardless of how strong every other " +
      "signal is. Contract safety and holder distribution are not collected, so " +
      "this list is a floor on risk, never a clearance for anything absent from it.",
  },
];

export interface SectionInput {
  scored: TopScoreEntry[];
  radar: RadarEntry[];
  /** mint -> Exit Watch severity, when assessed. */
  exitSeverity: Map<string, string>;
}

export interface SectionResult {
  definition: SectionDefinition;
  mints: string[];
}

const RADAR_MOMENTUM = new Set(["early_momentum", "breakout"]);

/**
 * Assign tokens to sections.
 *
 * A token may appear in more than one section — that is deliberate. A project
 * can genuinely be both gaining liquidity and losing strength, and hiding one
 * of those to keep the page tidy would be the product choosing which fact the
 * user is allowed to see.
 */
export function buildSections(input: SectionInput, limit = 6): SectionResult[] {
  const { scored, radar, exitSeverity } = input;

  const byId: Record<string, string[]> = {
    // The engine's own top bands, in the order it ranked them.
    highest_conviction: scored
      .filter((item) => item.score?.grade === "high_conviction" || item.score?.is_elite)
      .map((item) => item.token.mint_address),

    building_momentum: radar
      .filter((entry) => RADAR_MOMENTUM.has(entry.category))
      .map((entry) => entry.mint_address),

    increasing_liquidity: radar
      .filter((entry) => entry.detection_reason.includes("liquidity_growing"))
      .map((entry) => entry.mint_address),

    early_accumulation: radar
      .filter((entry) => entry.category === "undervalued")
      .map((entry) => entry.mint_address),

    recovery: radar
      .filter((entry) => belowPeak(entry))
      .map((entry) => entry.mint_address),

    losing_strength: radar
      .filter((entry) => {
        const severity = exitSeverity.get(entry.mint_address);
        return severity === "watch" || severity === "elevated";
      })
      .map((entry) => entry.mint_address),

    highest_risk: [
      ...scored
        .filter((item) => item.score?.risk?.has_veto)
        .map((item) => item.token.mint_address),
      ...radar
        .filter((entry) => exitSeverity.get(entry.mint_address) === "elevated")
        .map((entry) => entry.mint_address),
    ],
  };

  // Fall back to the strongest band the engine did award when nothing reached
  // high conviction — an empty lead section on a live platform reads as broken,
  // and "nothing qualified today" is better said than implied.
  if ((byId.highest_conviction ?? []).length === 0) {
    byId.highest_conviction = scored
      .filter((item) => item.score?.grade === "strong")
      .map((item) => item.token.mint_address);
  }

  return SECTIONS.map((definition) => ({
    definition,
    mints: [...new Set(byId[definition.id] ?? [])].slice(0, limit),
  }));
}

/** True when a token trades below the peak it reached after detection. */
function belowPeak(entry: RadarEntry): boolean {
  if (!entry.current_multiple || !entry.peak_multiple) return false;
  return Number(entry.current_multiple) < Number(entry.peak_multiple);
}
