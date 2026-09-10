import type { Tile } from "./geometry";
import type { ZoneId } from "./zones";

/**
 * THE ROSTER.
 *
 * Fourteen people. Thirteen stand for one MEMESCOPE subsystem each; the
 * fourteenth, Karthik, stands for one experiment being run properly. Defined once, as
 * data, because the brief's requirement is explicit: employee information must
 * not be spread through UI components. The stage, the tablet zone view, the
 * mobile card list and the accessible description all read this array, so they
 * cannot disagree about who exists or what they do.
 *
 * WHAT IS DELIBERATELY ABSENT
 *
 * No metrics, no counts, no status. HQ-1 is a static shell and this file must
 * not grow a `tokensReviewed: 1284` field — an invented statistic is the one
 * failure this whole feature cannot survive. Live state arrives in HQ-3 from
 * the adapter, keyed by `id`, and is merged at render time.
 *
 * `systemResponsibility` is prose for a human reading a panel. It is not a
 * data source and nothing derives behaviour from it.
 */

export type EmployeeId =
  | "nova"
  // Discovery is ONE desk. Luna and Dex were retired on 2026-09-08: all three
  // derived from the same `activity` source and nothing else, so the floor
  // showed three people reacting to one number. Three desks watching one
  // reading is not depth, it is an echo.
  | "radar"
  | "atlas"
  | "milo"
  | "rex"
  | "echo"
  | "byte"
  // The reliability trio. Added when HQ stopped being a window onto MEMESCOPE
  // and started being able to act on it: somebody has to notice a component
  // has failed, somebody has to diagnose it, and somebody has to prove the
  // repair worked before it is believed. Those are three different jobs and
  // giving them to one person is how a system ends up marking its own homework.
  | "sentinel"
  | "patch"
  | "quinn"
  | "vault"
  // The Karthik Paper Wallet's dedicated operator. Added because that wallet is
  // a *separate experiment* with a separate mandate: nobody already on this
  // roster may touch it, and nobody on it may touch anything else. A desk that
  // exists precisely to be isolated is a desk, not a second hat on Sentinel.
  | "karthik"
  // RAFIQ ANALYTICS. Five desks, one per strategy in the Rafiq Lab, in a room
  // of their own. Five people rather than one "lab analyst" because the lab
  // runs five *separate books* with five separate rules and one shared feed:
  // a single desk covering all five would average them, and averaging is
  // precisely the mistake that makes five arms look like one result.
  | "anchor"
  | "tempo"
  | "sigma"
  | "halt"
  | "chorus";

/**
 * The normalised states from the plan. Declared now so the shell's types are
 * final, but HQ-1 renders every employee as `unknown` — nothing is measured
 * yet, and `idle` would read as "measured, and quiet".
 */
export type EmployeeState =
  | "unknown"
  | "offline"
  | "idle"
  | "working"
  | "busy"
  | "reviewing"
  | "success"
  | "alert"
  | "error"
  // Autonomy states. Each requires an open record on the backend to be shown —
  // `investigating` and `verifying` name a mission id, `incident` names an
  // incident. There is no path that reaches these three from a timer.
  | "investigating"
  | "verifying"
  | "incident";

/**
 * The org chart, which is not the floor plan.
 *
 * `zone` says which room a desk stands in; `department` says who somebody
 * belongs to. They agree for ten of the thirteen and disagree for Patch, whose
 * bench is in the Performance Lab because Operations had one free tile and
 * Sentinel needed it. Keeping them as separate fields is what stops a seating
 * accident from silently rewriting the org chart — §19 of the brief groups
 * people by department, and no amount of furniture should change that.
 */
export type DepartmentId =
  | "command"
  | "discovery"
  | "market"
  | "risk"
  | "portfolio"
  | "operations"
  | "infrastructure"
  | "research"
  | "karthik_lab"
  | "execution"
  | "qa"
  | "rafiq_analytics";

export const DEPARTMENT_LABEL: Record<DepartmentId, string> = {
  command: "Command",
  discovery: "Discovery & Intelligence",
  market: "Market & Execution",
  risk: "Risk",
  portfolio: "Portfolio",
  operations: "Operations",
  infrastructure: "Infrastructure",
  research: "Performance & Research",
  qa: "Quality Assurance",
  karthik_lab: "Karthik Lab",
  execution: "Execution",
  rafiq_analytics: "Rafiq Analytics",
};

export interface Employee {
  id: EmployeeId;
  name: string;
  role: string;
  zone: ZoneId;
  /** Who they report with. Independent of which room the desk is in. */
  department: DepartmentId;
  /** Desk anchor, in tile coordinates. The person stands here. */
  desk: Tile;
  /** Which subsystem this person is. Shown in the panel; never used as data. */
  systemResponsibility: string;
  /**
   * How this person introduces themselves in public, in their own voice.
   *
   * Written for the homepage's crew section rather than for the HQ panel:
   * `systemResponsibility` is a list of subsystems, which is what an operator
   * needs and what a visitor bounces off. Both describe the same job.
   *
   * **Neither may make a claim.** These sentences say what a desk watches, not
   * how well it is going — the same rule every other string in HQ lives under.
   */
  whatIDo: string;
  /** The colleagues this desk actually hands work to, by id. */
  worksWith: EmployeeId[];
  /** Idle vocabulary, for HQ-4. Presentation only — never implies system state. */
  personality: string;
  /** Silhouette accessory that makes them recognisable without a label. */
  accessory: string;
  /**
   * Palette key, resolved to CSS custom properties in `hq.css`. A key rather
   * than a hex value so the theme stays in one place and dark/light and any
   * future high-contrast mode do not need this file edited.
   */
  palette: string;
}

export const EMPLOYEES: Employee[] = [
  {
    id: "nova",
    name: "Nova",
    role: "CEO / Commander",
    zone: "mission",
    department: "command",
    desk: { col: 8, row: 1 },
    systemResponsibility: "Overall system status, portfolio roll-up, daily brief",
    whatIDo:
      "Watches the whole platform, decides what needs attention, and pulls the team together when the picture has to be assembled in one place.",
    worksWith: ["radar","atlas","milo"],
    personality: "Calm and observant. Patrols the floor, pauses at departments.",
    accessory: "tablet",
    palette: "indigo",
  },
  {
    id: "radar",
    name: "Radar",
    role: "Head of Discovery",
    zone: "floor",
    department: "discovery",
    desk: { col: 6, row: 3 },
    systemResponsibility: "Scanner, token discovery, Radar admission",
    whatIDo:
      "Watches the scanner for tokens that have just appeared, and keeps an eye on the ones that have started to move.",
    worksWith: ["atlas", "milo"],
    personality: "Energetic and fast. Leans into the feed, spins the dish.",
    accessory: "headset",
    palette: "cyan",
  },
  {
    id: "atlas",
    name: "Atlas",
    role: "Chief Risk Officer",
    zone: "risk",
    department: "risk",
    desk: { col: 2, row: 4 },
    systemResponsibility:
      "Safety gate, liquidity security, mint and freeze authority, price impact",
    whatIDo:
      "Checks mint and freeze authority, the venue and the liquidity behind a token before any entry is allowed.",
    worksWith: ["rex","nova"],
    personality: "Serious and still. Deliberate scans. Rarely moves.",
    accessory: "shield",
    palette: "steel",
  },
  {
    id: "rex",
    name: "Rex",
    role: "Execution Specialist",
    zone: "floor",
    department: "market",
    desk: { col: 12, row: 4 },
    systemResponsibility: "Paper Wallet entries and exits; Real Wallet state display",
    whatIDo:
      "Watches Paper Wallet entries and exits, the execution quotes behind them and how each position actually closed.",
    worksWith: ["atlas","milo"],
    personality: "Confident and fast. Drums fingers, rolls the chair back.",
    accessory: "wrist-terminal",
    palette: "crimson",
  },
  {
    id: "milo",
    name: "Milo",
    role: "Portfolio Manager",
    zone: "portfolio",
    department: "portfolio",
    desk: { col: 2, row: 8 },
    systemResponsibility: "Open positions, exposure, holding period, capital efficiency",
    whatIDo:
      "Tracks what capital is doing: open positions, exposure, holding periods and which generation is trading.",
    worksWith: ["rex","nova"],
    personality: "Patient and strategic. Steps back from the wall, arms folded.",
    accessory: "clipboard",
    palette: "forest",
  },
  {
    id: "echo",
    name: "Echo",
    role: "Operations Manager",
    zone: "ops",
    department: "operations",
    desk: { col: 6, row: 8 },
    systemResponsibility: "Workers, queues, enrichment backlog, priority lane",
    whatIDo:
      "Keeps the enrichment queues moving and watches the priority lane for anything waiting longer than it should.",
    worksWith: ["byte"],
    personality: "Organised and mobile. Walks between terminals, gestures at the board.",
    accessory: "tool-belt",
    palette: "orange",
  },
  {
    id: "byte",
    name: "Byte",
    role: "Infrastructure Engineer",
    zone: "ops",
    department: "infrastructure",
    desk: { col: 9, row: 8 },
    systemResponsibility: "Database, cache, RPC, WebSocket and API health",
    whatIDo:
      "Watches the database, cache, RPC, WebSocket and API — the parts that have to be up for anything else to be true.",
    worksWith: ["echo","nova"],
    personality: "Technical and slouched. Three mugs. Stretches, refills, occasionally naps.",
    accessory: "hoodie",
    palette: "lime",
  },
  {
    id: "sentinel",
    name: "Sentinel",
    role: "Production / SRE",
    zone: "ops",
    department: "infrastructure",
    // The one tile Operations had left. Everything else in this room is a
    // desk, a cabinet, the printer Sam services, or an authored walk route.
    desk: { col: 6, row: 9 },
    systemResponsibility:
      "Container, Redis, Postgres, Celery, scheduler, disk and queue health",
    whatIDo:
      "Watches the machinery the platform runs on — containers, broker, database, workers and disk — and raises an incident the moment one of them stops answering.",
    worksWith: ["byte", "patch", "nova"],
    personality: "Watchful and unhurried. Stands at the wall, scans, sits down again.",
    accessory: "visor",
    palette: "ice",
  },
  {
    id: "patch",
    name: "Patch",
    role: "Reliability Engineer",
    // Physically in the Performance Lab, because Operations had exactly one
    // free tile and Sentinel took it. `department` is what §19 cares about and
    // it still says infrastructure — real departments span rooms, and the
    // alternative was wedging a desk onto a walk route.
    zone: "lab",
    department: "infrastructure",
    desk: { col: 12, row: 9 },
    systemResponsibility:
      "Incident diagnosis, remediation execution, backend defect investigation",
    whatIDo:
      "Takes an open incident, works out which component actually failed, and either applies a permitted repair or writes up what a person needs to decide.",
    worksWith: ["sentinel", "byte", "quinn"],
    personality: "Methodical. Reads the evidence before touching anything.",
    accessory: "toolbox",
    palette: "rust",
  },
  {
    id: "quinn",
    name: "Quinn",
    role: "QA / Verification Engineer",
    zone: "lab",
    department: "qa",
    // The lab's north-east corner. (14,8) was legal but had one exit, south
    // into the Lounge — a verification desk should not have to walk through
    // the sofa to reach a meeting.
    desk: { col: 15, row: 7 },
    systemResponsibility:
      "Post-repair verification, protected-invariant checks, recovery confirmation",
    whatIDo:
      "Re-checks a component after a repair and confirms the protected trading rules are byte-for-byte what they were before it, so nothing is called fixed on hope.",
    worksWith: ["patch", "sentinel"],
    personality: "Sceptical by trade. Asks for the second reading.",
    accessory: "glasses",
    palette: "mint",
  },
  {
    // KARTHIK.
    //
    // The one desk on this roster whose *authority* is narrower than its
    // curiosity. He reads the Karthik Paper Wallet exhaustively — every
    // opportunity, entry, open position, target, dead token and accounting
    // event — and he is permitted to change almost none of it. Seven
    // operational repairs are allowlisted; the wallet's rules, its capital,
    // its sizing and its history are not among them, and nothing on this floor
    // can widen that list without a code change.
    //
    // He is also the only person here who is *not* a MEMESCOPE subsystem. The
    // other thirteen stand for something the platform runs; Karthik stands for
    // one experiment being run *properly*, which is a different job and gets a
    // different room.
    id: "vault",
    name: "Vault",
    role: "Execution Wallet Custodian",
    zone: "vault",
    department: "execution",
    // Inside the sealed room, not beside it. The Execution Vault has had a
    // footprint and a summary since HQ-1 and nobody in it, because there was
    // nothing to watch: mainnet submission was refused by two code constants.
    // Those were reviewed and turned off, the wallet is funded, and a room with
    // real money in it and no occupant is the one room that needs one.
    desk: { col: 14, row: 3 },
    systemResponsibility:
      "Execution wallet: balance, intents, the isolated signer, the withdrawal address, the kill switch",
    whatIDo:
      "I watch the one wallet that can spend real money. I read where each intent stopped and why, whether the signer still holds the pinned key, and whether the balance moved without a confirmed intent behind it. I authorise nothing — the guard and the transport policy decide that, and I only ever report.",
    // Atlas because safety decides what may be entered at all; Rex because the
    // paper desk runs the same strategies without the money; Nova because an
    // owner-attention item has to reach somebody who can decide.
    worksWith: ["atlas", "rex", "nova"],
    personality:
      "Still, and slow to speak. Sits facing the door rather than the floor. Says the reason, never the reassurance.",
    accessory: "keyring",
    palette: "slate",
  },
  {
    id: "karthik",
    name: "Karthik",
    role: "Paper Wallet Operator",
    zone: "karthik",
    department: "karthik_lab",
    // Centre of the lab, with all four neighbours clear: north to the deck and
    // the rest of the building, west to the counter, east to the wall display,
    // south to Satoshi's corner. Every authored route out of this room starts
    // on one of those four tiles.
    desk: { col: 18, row: 9 },
    systemResponsibility:
      "Karthik Paper Wallet and Strategy Lab monitoring, audit, safe auto-repair, reporting and owner escalation",
    // The Lab watch was added on the owner's instruction, 2026-09-04. It widens
    // the isolation note above: this desk now also watches the Strategy Lab
    // tournament, because all four `lab:` conditions were being DETECTED with
    // no repair attached and a wedged queue would stop the tournament unseen.
    //
    // The isolation that matters is unchanged and is enforced in the backend,
    // not here: the two Lab repairs re-enqueue the Lab's own beat tasks and can
    // open nothing, close nothing, pick no strategy and reach no wallet.
    whatIDo:
      "I watch every Karthik Paper Wallet opportunity, entry, open position, target, dead token and accounting event, and I keep the Strategy Lab tournament running. I repair the small operational failures that cannot change a result, and I escalate anything that needs the owner's judgement.",
    // Radar and Atlas because the wallet's universe is theirs; Byte because
    // the machinery underneath is his; Nova because an owner-attention item
    // has to reach somebody who can decide.
    worksWith: ["radar", "atlas", "byte", "nova"],
    personality: "Fast hands, narrow remit. Reads the evidence, then says what he cannot do.",
    accessory: "headphones",
    palette: "magenta",
  },

  /* ── RAFIQ ANALYTICS ──────────────────────────────────────────────────
   *
   * One analyst per Rafiq Lab strategy, assigned by Nova on 2026-09-10.
   *
   * WHY FIVE PEOPLE AND NOT ONE.
   *
   * The lab runs five books with five different rules over one shared feed.
   * A single desk covering all five would have to speak about them in
   * aggregate, and the aggregate is meaningless here — the arms disagree by
   * design, which is the entire experiment. Strategy B wins 64% of its trades
   * and still loses money while Strategy A wins 30%; averaged together those
   * two facts vanish, and the vanishing is the failure.
   *
   * WHAT THESE DESKS MAY SAY.
   *
   * They read `/labs/rafiq/analysis`, which computes arithmetic over the
   * lab's own position rows and nothing else. They report figures with the
   * columns behind them, and where a finding points anywhere it names a
   * measurable quantity rather than an outcome. None of them proposes a rule
   * change, ranks the arms, or forecasts a return — those are the claims eight
   * recorded no-edge findings on this platform were unable to support, and a
   * cartoon analyst asserting them anyway would be the least trustworthy thing
   * in the product.
   */
  {
    id: "anchor",
    name: "Anchor",
    role: "Strategy A Analyst",
    zone: "rafiq",
    department: "rafiq_analytics",
    // The five desks run west to east in strategy order, so the row reads
    // A-B-C-D-E left to right and a reader never has to hunt for an arm.
    // Three tiles apart, which is close enough that the five read as one
    // row shared by a team. They were four apart first and the room looked
    // like five people who happened to be in the same postcode.
    desk: { col: 6, row: 16 },
    systemResponsibility:
      "Rafiq Lab Strategy A (hard stop guard): open positions, closed trades, exit reasons and execution cost",
    whatIDo:
      "I read Strategy A's closed trades and ask one question of every loser: was the stop the thing that cost it, or was the entry? The peak price each position reached answers that, and I do not guess when it does not.",
    // Every analyst works with the other four. Strategy E only enters when the
    // arms agree, so the room's readings genuinely depend on each other rather
    // than five people sitting near one another.
    worksWith: ["tempo", "sigma", "halt", "chorus"],
    personality: "Deliberate and blunt. Rereads a trade before saying anything about it.",
    accessory: "glasses",
    palette: "brass",
  },
  {
    id: "tempo",
    name: "Tempo",
    role: "Strategy B Analyst",
    zone: "rafiq",
    department: "rafiq_analytics",
    // The five desks run west to east in strategy order, so the row reads
    // A-B-C-D-E left to right and a reader never has to hunt for an arm.
    // Three tiles apart, which is close enough that the five read as one
    // row shared by a team. They were four apart first and the room looked
    // like five people who happened to be in the same postcode.
    desk: { col: 9, row: 16 },
    systemResponsibility:
      "Rafiq Lab Strategy B (time boxed exit): open positions, closed trades, exit reasons and execution cost",
    whatIDo:
      "I read Strategy B's holds. It is the arm that exits on time rather than on price, so my whole record is about what the clock caught and what it cut short.",
    // Every analyst works with the other four. Strategy E only enters when the
    // arms agree, so the room's readings genuinely depend on each other rather
    // than five people sitting near one another.
    worksWith: ["anchor", "sigma", "halt", "chorus"],
    personality: "Quick and precise. Speaks in elapsed minutes and taps a rhythm on the desk.",
    accessory: "stylus",
    palette: "violet",
  },
  {
    id: "sigma",
    name: "Sigma",
    role: "Strategy C Analyst",
    zone: "rafiq",
    department: "rafiq_analytics",
    // The five desks run west to east in strategy order, so the row reads
    // A-B-C-D-E left to right and a reader never has to hunt for an arm.
    // Three tiles apart, which is close enough that the five read as one
    // row shared by a team. They were four apart first and the room looked
    // like five people who happened to be in the same postcode.
    desk: { col: 12, row: 16 },
    systemResponsibility:
      "Rafiq Lab Strategy C (volatility adjusted risk): open positions, closed trades, exit reasons and execution cost",
    whatIDo:
      "I read Strategy C, the arm that sets its own stop from the volatility it measured at entry. My job is to check the measurement against what the position then did.",
    // Every analyst works with the other four. Strategy E only enters when the
    // arms agree, so the room's readings genuinely depend on each other rather
    // than five people sitting near one another.
    worksWith: ["anchor", "tempo", "halt", "chorus"],
    personality: "Careful and slow to commit. Will not give a figure without saying how wide it is.",
    accessory: "loupe",
    palette: "cobalt",
  },
  {
    id: "halt",
    name: "Halt",
    role: "Strategy D Analyst",
    zone: "rafiq",
    department: "rafiq_analytics",
    // The five desks run west to east in strategy order, so the row reads
    // A-B-C-D-E left to right and a reader never has to hunt for an arm.
    // Three tiles apart, which is close enough that the five read as one
    // row shared by a team. They were four apart first and the room looked
    // like five people who happened to be in the same postcode.
    desk: { col: 15, row: 16 },
    systemResponsibility:
      "Rafiq Lab Strategy D (daily drawdown breaker): open positions, closed trades, exit reasons and execution cost",
    whatIDo:
      "I read Strategy D, the arm that stops itself when a day goes badly enough. Most of my record is days where nothing happened, and that is the point of it.",
    // Every analyst works with the other four. Strategy E only enters when the
    // arms agree, so the room's readings genuinely depend on each other rather
    // than five people sitting near one another.
    worksWith: ["anchor", "tempo", "sigma", "chorus"],
    personality: "Watchful and quiet. Keeps one eye on the day's line and says little until it moves.",
    accessory: "chart-roll",
    palette: "plum",
  },
  {
    id: "chorus",
    name: "Chorus",
    role: "Strategy E Analyst",
    zone: "rafiq",
    department: "rafiq_analytics",
    // The five desks run west to east in strategy order, so the row reads
    // A-B-C-D-E left to right and a reader never has to hunt for an arm.
    // Three tiles apart, which is close enough that the five read as one
    // row shared by a team. They were four apart first and the room looked
    // like five people who happened to be in the same postcode.
    desk: { col: 18, row: 16 },
    systemResponsibility:
      "Rafiq Lab Strategy E (ensemble guarded): open positions, closed trades, exit reasons and execution cost",
    whatIDo:
      "I read Strategy E. It waits for consensus before it enters, so I spend more time reading the other four desks' books than my own — and when mine is empty, that is a reading and not a gap.",
    // Every analyst works with the other four. Strategy E only enters when the
    // arms agree, so the room's readings genuinely depend on each other rather
    // than five people sitting near one another.
    worksWith: ["anchor", "tempo", "sigma", "halt"],
    personality: "Attentive to everyone else's screen. Rolls the chair down the row to check a number.",
    accessory: "visor",
    palette: "clay",
  },
];

export const EMPLOYEE_BY_ID = new Map<EmployeeId, Employee>(
  EMPLOYEES.map((employee) => [employee.id, employee]),
);

export function employeesInZone(zone: ZoneId): Employee[] {
  return EMPLOYEES.filter((employee) => employee.zone === zone);
}

/**
 * How a state should read to someone who cannot see colour, and what it is
 * called in an accessible name.
 *
 * `unknown` is first and is the HQ-1 default for every employee. It must never
 * present as healthy: no data is not the same as nothing happening, and the
 * green reading of an unmeasured system is the exact failure this product
 * cannot afford.
 */
export const STATE_LABEL: Record<EmployeeState, string> = {
  unknown: "No data",
  offline: "Offline",
  idle: "Idle",
  working: "Working",
  busy: "Busy",
  reviewing: "Reviewing",
  success: "Complete",
  alert: "Alert",
  error: "Error",
  investigating: "Investigating",
  verifying: "Verifying",
  incident: "Incident",
};

/** States that must never be styled as healthy. Asserted in tests. */
export const NON_HEALTHY_STATES: EmployeeState[] = [
  "unknown",
  "offline",
  "alert",
  "error",
  "incident",
];
