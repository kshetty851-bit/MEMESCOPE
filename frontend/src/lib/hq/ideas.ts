import { STALE_AFTER_MS, fresh, type HqState } from "./adapter";
import { EMPLOYEE_BY_ID, type EmployeeId } from "./employees";

/**
 * WHAT THE FLOOR THINKS IS WORTH BUILDING NEXT.
 *
 * ── THE PROBLEM THIS HAD TO SOLVE FIRST ─────────────────────────────────
 *
 * A room full of characters offering opinions is the easiest thing in this
 * codebase to get wrong, and it would be wrong in the specific way the whole
 * product is built to avoid. Every other sentence in HQ is refused unless a
 * reading stands behind it — chatter says nothing about the system precisely
 * because it fires on a timer. An "idea" is an opinion, and an opinion with
 * nothing behind it is the same fabrication wearing a friendlier face.
 *
 * So an idea here is not generated. It is **derived**, and it carries its own
 * evidence:
 *
 *     because  — the measured fact, WITH the number, in one sentence
 *     source   — the field that number came from
 *
 * If the reading is missing, stale, or the threshold is not crossed, there is
 * no idea. Not a placeholder, not a softer version — nothing. That is why
 * `ideasFrom` can return an empty list and why the panel says so plainly
 * rather than filling the space.
 *
 * ── WHY THE SUGGESTIONS ARE SMALL ───────────────────────────────────────
 *
 * None of these proposes a strategy, and that is deliberate rather than shy.
 * This platform has now recorded eight separate no-edge findings; a cartoon
 * character proposing "try momentum" would be inventing the one kind of claim
 * the research has most expensively earned the right to refuse. What a desk
 * can honestly propose is work on the thing it measures — the queue it can
 * see, the disk it can see, the gap in its own evidence. That is a smaller
 * claim and it is one the number actually supports.
 */

export type Urgency = "now" | "soon" | "worth doing";

export interface Idea {
  /** Stable across renders: keys and tests both depend on it not moving. */
  id: string;
  from: EmployeeId;
  /** What to do, imperative, short enough to read at a glance. */
  headline: string;
  /** The measured fact behind it. Must contain the figure, not describe it. */
  because: string;
  /** Where that figure came from. Rendered next to it, like every HQ metric. */
  source: string;
  urgency: Urgency;
}

const ORDER: Record<Urgency, number> = { now: 0, soon: 1, "worth doing": 2 };

/** Round for display without pretending to precision the source lacks. */
function pct(value: number): string {
  return `${Math.round(value)}%`;
}

/**
 * Every rule, in one list.
 *
 * Each returns `null` far more often than it returns an idea, which is the
 * intended shape: a quiet, healthy platform should produce an empty board.
 */
export function ideasFrom(state: HqState): Idea[] {
  const out: Idea[] = [];
  const ops = fresh(state.sources.operations, STALE_AFTER_MS.operations, state.now);
  const karthik = fresh(state.sources.karthik, STALE_AFTER_MS.karthik, state.now);

  /* ---- Byte: the disk, which has taken this platform down twice --------- */
  if (ops?.health.disk.measured && ops.health.disk.percent_used !== null) {
    const used = ops.health.disk.percent_used;
    const warn = ops.health.disk.warning_percent;
    if (used >= warn) {
      out.push({
        id: "disk-headroom",
        from: "byte",
        headline: "Free disk before the next deploy needs the room",
        because: `The volume is ${pct(used)} full against a ${pct(warn)} warning line, and a deploy dumps the database before it migrates.`,
        source: "GET /hq · health.disk.percent_used",
        urgency: used >= ops.health.disk.critical_percent ? "now" : "soon",
      });
    }
  }

  /* ---- Echo: work waiting for a worker --------------------------------- */
  if (ops?.health.queues.measured && ops.health.queues.total !== null) {
    const total = ops.health.queues.total;
    // A deep queue is a reading; a deep queue is not automatically a problem,
    // so this is the one rule with a deliberately high bar.
    if (total >= 500) {
      const deepest = Object.entries(ops.health.queues.depths).sort((a, b) => b[1] - a[1])[0];
      out.push({
        id: "queue-depth",
        from: "echo",
        headline: "Find out what is filling the queue faster than it drains",
        because: `${total} messages are waiting${deepest ? `, ${deepest[1]} of them on ${deepest[0]}` : ""}.`,
        source: "GET /hq · health.queues.total",
        urgency: total >= 2000 ? "now" : "soon",
      });
    }
  }

  /* ---- Patch and Quinn: the operational record -------------------------- */
  if (ops) {
    const owner = ops.incidents.filter((incident) => incident.status === "awaiting_owner");
    if (owner.length > 0) {
      out.push({
        id: "owner-queue",
        from: "patch",
        headline: "Clear the items only you can decide",
        because: `${owner.length} incident${owner.length === 1 ? "" : "s"} are waiting on an owner decision, the oldest being ${owner[owner.length - 1]!.code}.`,
        source: "GET /hq · incidents[status=awaiting_owner]",
        urgency: owner.length >= 5 ? "soon" : "worth doing",
      });
    }
    const failed = ops.activity.filter((action) => action.outcome === "failed");
    if (failed.length > 0) {
      out.push({
        id: "failed-repairs",
        from: "quinn",
        headline: "Look at the repairs that ran and did not work",
        because: `${failed.length} of the last ${ops.activity.length} recorded actions failed, most recently ${failed[0]!.action}.`,
        source: "GET /hq · activity[outcome=failed]",
        urgency: "soon",
      });
    }
  }

  /* ---- Sentinel: the labs, which are the experiment ---------------------- */
  for (const lab of ops?.health.labs ?? []) {
    if (!lab.measured) continue;
    const name = lab.label ?? "a lab";
    if (lab.stale_pct !== null && lab.stale_pct !== undefined && lab.stale_pct >= 50) {
      out.push({
        id: `lab-stale-${name}`,
        from: "sentinel",
        headline: `Give ${name} a price it can trust`,
        because: `${pct(lab.stale_pct)} of its open positions cannot be priced from a fresh snapshot or a fresh quote.`,
        source: "GET /hq · health.labs[].stale_pct",
        urgency: "soon",
      });
    }
    if (
      lab.minutes_since_decision !== null &&
      lab.minutes_since_decision !== undefined &&
      lab.minutes_since_decision >= 60
    ) {
      out.push({
        id: `lab-quiet-${name}`,
        from: "sentinel",
        headline: `Check why ${name} has stopped deciding`,
        because: `Its last entry decision was ${Math.round(lab.minutes_since_decision)} minutes ago.`,
        source: "GET /hq · health.labs[].minutes_since_decision",
        urgency: lab.minutes_since_decision >= 180 ? "now" : "soon",
      });
    }
  }

  /* ---- Karthik: his own experiment's integrity -------------------------- */
  if (karthik?.binding.readable) {
    const worst = [...karthik.integrity.deductions]
      .filter((d) => d.measured && d.penalty > 0)
      .sort((a, b) => b.penalty - a.penalty)[0];
    if (worst) {
      out.push({
        id: `karthik-${worst.factor}`,
        from: "karthik",
        headline: `Close the biggest hole in the wallet's evidence: ${worst.label.toLowerCase()}`,
        because: `${worst.detail} That is ${worst.penalty} of the ${100 - (karthik.integrity.score ?? 0)} points off this experiment's integrity score.`,
        source: "GET /karthik-ops · integrity.deductions",
        urgency: worst.penalty >= 15 ? "soon" : "worth doing",
      });
    }
    const unmeasured = karthik.integrity.deductions.filter((d) => !d.measured);
    if (unmeasured.length > 0) {
      out.push({
        id: "karthik-unmeasured",
        from: "karthik",
        headline: "Make the unmeasurable parts of the wallet measurable",
        because: `${unmeasured.length} of ${karthik.integrity.deductions.length} integrity factors cannot be read at all, starting with ${unmeasured[0]!.label.toLowerCase()}.`,
        source: "GET /karthik-ops · integrity.deductions[measured=false]",
        urgency: "worth doing",
      });
    }
  }

  /* ---- Nova: the gaps in HQ's own sight --------------------------------- *
   *
   * The roll-up desk proposes the thing every other rule here depends on. A
   * desk with no reading cannot raise an idea of its own — it is definitionally
   * silent — so somebody has to notice the silence, and that is the job this
   * character already has.
   */
  // Gated on `ops`, and the gate is the point. With no sources at all every
  // desk reads `unknown`, so an ungated rule announces "11 of 12 desks are
  // blind" on the first paint of every page load — which is the loading state
  // wearing a finding's clothes. A live operations reading is the cheapest
  // proof that HQ is actually talking to the backend, and only then is a
  // silent desk a gap rather than a page that has not finished loading.
  const blind = ops
    ? (Object.keys(state.employees) as EmployeeId[]).filter(
        (id) =>
          id !== "nova" &&
          state.employees[id].sourced &&
          state.employees[id].state === "unknown",
      )
    : [];
  if (blind.length > 0) {
    out.push({
      id: "blind-desks",
      from: "nova",
      headline: "Give the desks that report nothing something to report",
      because: `${blind.length} of ${Object.keys(state.employees).length} desks have no current reading: ${blind
        .map((id) => EMPLOYEE_BY_ID.get(id)?.name ?? id)
        .join(", ")}.`,
      source: "HQ roll-up · employees[].state",
      urgency: blind.length >= 4 ? "soon" : "worth doing",
    });
  }

  /* ---- Atlas: what HQ still cannot see at all --------------------------- *
   *
   * Not a threshold — a standing gap, and the most valuable thing on this
   * board precisely because no number will ever cross a line to announce it.
   * HQ measures liveness. It has never measured whether the answers are right,
   * and on 2026-08-26 it was solid green while the Lab froze most of its book.
   */
  if (ops) {
    out.push({
      id: "liveness-not-correctness",
      from: "atlas",
      headline: "Watch outcomes, not just heartbeats",
      because: `Every one of the ${ops.allowlist.length} things HQ may do is a restart or a re-run; nothing here checks that a component's answers are correct, only that it answered.`,
      source: "GET /hq · allowlist",
      urgency: "worth doing",
    });
  }

  return out.sort((a, b) => ORDER[a.urgency] - ORDER[b.urgency] || a.id.localeCompare(b.id));
}
