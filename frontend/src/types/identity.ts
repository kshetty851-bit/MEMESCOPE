/**
 * Clone-risk contracts.
 *
 * Mirrors `backend/app/schemas/identity.py`. `explanation` arrives as a
 * finished sentence and is displayed verbatim — the client never composes or
 * parses it, for the same reason it never composes a score reason.
 */

export type CloneRisk = "none" | "low" | "moderate" | "high";
export type IdentityConfidence = "high" | "moderate" | "low";

export interface TokenIdentity {
  mint_address: string;
  /** Tokens sharing this exact name, including this one. 1 means unique. */
  sharing_name: number;
  discovered_before: number;
  /** Earliest *observed*, which is not the same as earliest in existence. */
  is_earliest_known: boolean;
  clone_risk: CloneRisk;
  identity_confidence: IdentityConfidence;
  explanation: string;
}

export interface IdentityPage {
  items: TokenIdentity[];
}
