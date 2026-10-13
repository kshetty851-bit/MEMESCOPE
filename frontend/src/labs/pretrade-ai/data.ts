import { z } from "zod";

export const decisions = ["ACCEPT", "REVIEW", "REJECT", "INSUFFICIENT_DATA"] as const;
export type Decision = (typeof decisions)[number];
export const labels: Record<Decision, string> = {
  ACCEPT: "Passes research threshold",
  REVIEW: "Needs review",
  REJECT: "Filtered out",
  INSUFFICIENT_DATA: "Missing evidence",
};
const scoreSchema = z.object({
  schema_version: z.literal("1.0"),
  opportunity_id: z.string().min(1).max(500),
  mint: z.string().min(1).max(500),
  pool: z.string().min(1).max(500),
  decision_ts: z.string().datetime({ offset: true }),
  decision: z.enum(decisions),
  score: z.number().finite().min(0).max(100),
  model_probability: z.number().min(0).max(1).nullable(),
  liquidity_prior: z.number().finite().min(0).max(100),
  creator_funder_risk_score: z.number().finite().min(0).max(100),
  feature_completeness: z.number().min(0).max(1),
  reasons: z.array(z.string().max(2000)).max(100),
  model_version: z.string().max(200),
  execution_authorized: z.literal(false),
  production_write_authorized: z.literal(false),
  integration_contract: z.object({
    mode: z.literal("advisory_only"),
    may_execute_trade: z.literal(false),
    may_modify_production: z.literal(false),
    consumer_must_revalidate_at_use_time: z.literal(true),
  }),
});
export type Score = z.infer<typeof scoreSchema>;
export const MAX_BYTES = 5 * 1024 * 1024;
export function parseScores(text: string): Score[] {
  if (new TextEncoder().encode(text).length > MAX_BYTES)
    throw new Error("Choose a file smaller than 5 MB.");
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) throw new Error("This file has no score records.");
  if (lines.length > 5000) throw new Error("Open up to 5,000 score records at a time.");
  const seen = new Set<string>();
  return lines.map((line, index) => {
    let raw: unknown;
    try {
      raw = JSON.parse(line);
    } catch {
      throw new Error(`Record ${index + 1} is not valid JSON.`);
    }
    const parsed = scoreSchema.safeParse(raw);
    if (!parsed.success)
      throw new Error(
        `Record ${index + 1} is not a valid advisory score export. Open scores.jsonl from the pre-trade lab.`,
      );
    if (seen.has(parsed.data.opportunity_id))
      throw new Error(`Record ${index + 1} repeats an opportunity ID.`);
    seen.add(parsed.data.opportunity_id);
    return parsed.data;
  });
}
