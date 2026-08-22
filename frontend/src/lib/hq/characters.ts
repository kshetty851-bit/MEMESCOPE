import type { EmployeeId } from "./employees";

/**
 * WHAT EACH PERSON LOOKS LIKE.
 *
 * Separate from `employees.ts` on purpose. That file says what someone *is* —
 * their subsystem, their desk tile, their department. This one says how they
 * are drawn. Keeping them apart means the roster can be read by the mobile
 * cards and the accessible description without dragging in a rendering
 * vocabulary, and a visual change never touches the operational definition.
 *
 * DIFFERENTIATION IS THE POINT, AND IT IS CHECKED
 *
 * The brief's requirement is that a reader can tell the cast apart with the
 * labels hidden and the status colours off. A palette swap cannot do that:
 * ten identical bodies in ten colours are ten of the same person. So every
 * character varies across several *shape* axes — build, hair, outfit,
 * accessory, posture — and a test asserts that no two share three or more of
 * them. Colour is the last axis, not the first.
 *
 * NOTHING HERE IS OPERATIONAL. A `deskTheme` draws abstract instrument shapes;
 * it never renders a number, because a number on a screen in this room would
 * read as a system fact and there are no system facts yet.
 */

/** Torso and shoulder shape. The strongest silhouette cue at 64px. */
export type BodyType = "slim" | "broad" | "tall" | "compact";

/** Head shape. Second-strongest, because it reads even when seated. */
export type HeadShape = "round" | "oval" | "square";

export type HairStyle =
  | "cropped"
  | "bun"
  | "wavy"
  | "curly-short"
  | "long-straight"
  | "tuft"
  | "buzz"
  | "ponytail"
  | "swept"
  | "locs"
  | "flat-top"
  | "shaggy"
  | "braid"
  // Karthik. Short and flat on the sides with volume left on top — the only
  // two-height crown in the cast, which is what makes it read at 64px beside
  // twelve silhouettes that are uniform all the way round.
  | "undercut";

/** Outfit silhouette, drawn as a distinct torso overlay. */
export type Outfit =
  | "blazer"
  | "field-jacket"
  | "cardigan"
  | "vest"
  | "yoke"
  | "hoodie"
  | "rolled-shirt"
  | "utility"
  | "long-coat"
  | "turtleneck"
  | "coveralls"
  | "parka"
  | "wrap-top"
  // Karthik. A zipped athletic jacket with raglan shoulders: the seam runs to
  // the collar instead of across the shoulder, so the outline has no square
  // corner where every tailored garment in the cast has one.
  | "track-jacket";

export type Accessory =
  | "duster"
  | "toolbox"
  | "tablet"
  | "headset"
  | "stylus"
  | "visor"
  | "shield-badge"
  | "clipboard"
  | "wrist-terminal"
  | "tool-belt"
  | "mug"
  | "glasses"
  | "pager"
  | "checklist"
  // Karthik's, worn *around the neck* rather than on the head. That is the
  // whole differentiation from Radar's headset: two cups sitting at the
  // collarbone read nothing like a band over the crown with a boom mic, and at
  // this size the position is the only cue that survives.
  | "headphones";

/**
 * Every pose the rig can draw.
 *
 * The first five are HQ-2's resting poses; the rest are HQ-3's ambient
 * vocabulary. They are all *presentation*. A pose never means a subsystem is
 * doing something — `seated_working` on Radar says "this office is staffed",
 * not "the scanner is scanning". HQ-4 introduces states that do carry meaning,
 * and they sit above this layer rather than replacing it.
 */
export type Pose =
  | "seated_working"
  | "seated_reviewing"
  | "standing"
  | "holding_tablet"
  | "coffee_idle"
  | "walking_short"
  | "stretching"
  | "looking_at_screen"
  | "talking_briefly"
  | "returning_to_desk"
  // World-expansion poses. `seated_lounge` and `seated_talk` sit a figure on
  // furniture that already exists at the destination — a sofa cushion or a
  // conference chair — so the rig draws no chair of its own. `tidying` is the
  // support staff's working stance: leaning slightly into a task.
  | "seated_lounge"
  | "seated_talk"
  | "tidying";

/** Poses that are drawn on two feet rather than in a chair. */
export const STANDING_POSES: ReadonlySet<Pose> = new Set<Pose>([
  "standing",
  "holding_tablet",
  "walking_short",
  "returning_to_desk",
  "stretching",
  "tidying",
]);

/**
 * Poses that sit on furniture at the destination rather than on an office
 * chair the rig conjures. The stage keeps everyone else away from their desk
 * on their feet; these are the exception, and the furniture they land on is
 * asserted to exist.
 */
export const SEATED_AWAY_POSES: ReadonlySet<Pose> = new Set<Pose>([
  "seated_lounge",
  "seated_talk",
]);

/** Which abstract instrument cluster sits on the desk. */
export type DeskTheme =
  | "mission"
  | "discovery"
  | "analysis"
  | "market"
  | "risk"
  | "portfolio"
  | "execution"
  | "operations"
  | "infrastructure"
  | "performance"
  | "sentry"
  | "reliability"
  | "verification"
  // Karthik's six-monitor wall. The only desk in the office with a screen
  // count as its identity, because a six-screen bench is what the job looks
  // like from across a room.
  | "wallet-ops";

/**
 * The visual half of a character, without the operational identity.
 *
 * The rig renders anything with this shape — the ten employees, and from the
 * world expansion also the two support staff, who are people the office
 * employs but not subsystems MEMESCOPE measures. Keeping the rig's input
 * structural is what lets the cast grow without the operational roster
 * growing with it.
 */
export interface CharacterLook {
  id: string;
  bodyType: BodyType;
  headShape: HeadShape;
  skinTone: "s1" | "s2" | "s3" | "s4" | "s5";
  hair: HairStyle;
  hairTone: "h1" | "h2" | "h3" | "h4" | "h5";
  outfit: Outfit;
  accessory: Accessory;
  palette: string;
  defaultPose: Pose;
}

export interface CharacterDefinition extends CharacterLook {
  id: EmployeeId;
  bodyType: BodyType;
  headShape: HeadShape;
  /**
   * Skin tone key, resolved to a CSS custom property. A key rather than a hex
   * so the whole cast can be retoned in one stylesheet, and so nobody has to
   * edit ten files to fix a contrast problem.
   */
  skinTone: "s1" | "s2" | "s3" | "s4" | "s5";
  hair: HairStyle;
  /** Hair colour key. Separate from skin: they vary independently. */
  hairTone: "h1" | "h2" | "h3" | "h4" | "h5";
  outfit: Outfit;
  accessory: Accessory;
  /** Garment colour key, matching `--hq-*` in `hq.css`. */
  palette: string;
  defaultPose: Pose;
  deskTheme: DeskTheme;
  /** One line, shown on the panel. Character, not system state. */
  personalityLine: string;
}

export const CHARACTERS: Record<EmployeeId, CharacterDefinition> = {
  nova: {
    id: "nova",
    bodyType: "tall",
    headShape: "oval",
    skinTone: "s4",
    hair: "swept",
    hairTone: "h1",
    outfit: "blazer",
    accessory: "tablet",
    palette: "indigo",
    // The only character who is never seated. Standing among seated colleagues
    // is what makes her read as the director without a label saying so.
    defaultPose: "standing",
    deskTheme: "mission",
    personalityLine: "Watches the whole mission. Rarely hurries.",
  },
  radar: {
    id: "radar",
    bodyType: "compact",
    headShape: "round",
    skinTone: "s2",
    hair: "cropped",
    hairTone: "h3",
    outfit: "field-jacket",
    accessory: "headset",
    palette: "cyan",
    defaultPose: "seated_working",
    deskTheme: "discovery",
    personalityLine: "First to see anything new. Leans into the feed.",
  },
  luna: {
    id: "luna",
    bodyType: "slim",
    headShape: "oval",
    skinTone: "s3",
    hair: "bun",
    hairTone: "h2",
    outfit: "turtleneck",
    accessory: "stylus",
    palette: "violet",
    defaultPose: "seated_reviewing",
    deskTheme: "analysis",
    personalityLine: "Reads the evidence twice before saying anything.",
  },
  dex: {
    id: "dex",
    bodyType: "slim",
    headShape: "square",
    skinTone: "s5",
    hair: "wavy",
    hairTone: "h4",
    outfit: "vest",
    accessory: "visor",
    palette: "amber",
    defaultPose: "seated_working",
    deskTheme: "market",
    personalityLine: "Four screens, one coffee, never still.",
  },
  atlas: {
    id: "atlas",
    bodyType: "broad",
    headShape: "square",
    skinTone: "s2",
    hair: "buzz",
    hairTone: "h5",
    outfit: "yoke",
    accessory: "shield-badge",
    palette: "steel",
    // Deliberately upright and still. Atlas is the one person who can stop the
    // pipeline, and stillness reads as authority where motion would read as
    // busywork.
    defaultPose: "seated_reviewing",
    deskTheme: "risk",
    personalityLine: "Says no more often than yes, and explains why.",
  },
  milo: {
    id: "milo",
    bodyType: "broad",
    headShape: "round",
    skinTone: "s1",
    hair: "curly-short",
    hairTone: "h2",
    outfit: "cardigan",
    accessory: "clipboard",
    palette: "forest",
    defaultPose: "standing",
    deskTheme: "portfolio",
    personalityLine: "Thinks in weeks. Watches what capital is doing.",
  },
  rex: {
    id: "rex",
    bodyType: "compact",
    headShape: "square",
    skinTone: "s3",
    hair: "ponytail",
    hairTone: "h5",
    outfit: "rolled-shirt",
    accessory: "wrist-terminal",
    palette: "crimson",
    defaultPose: "seated_working",
    deskTheme: "execution",
    personalityLine: "Precise, not reckless. Never trades on a hunch.",
  },
  echo: {
    id: "echo",
    bodyType: "tall",
    headShape: "round",
    skinTone: "s4",
    hair: "locs",
    hairTone: "h5",
    outfit: "utility",
    accessory: "tool-belt",
    palette: "orange",
    defaultPose: "standing",
    deskTheme: "operations",
    personalityLine: "Keeps the queues moving. Always mid-errand.",
  },
  byte: {
    id: "byte",
    bodyType: "slim",
    headShape: "round",
    skinTone: "s1",
    hair: "tuft",
    hairTone: "h4",
    outfit: "hoodie",
    accessory: "mug",
    palette: "lime",
    defaultPose: "coffee_idle",
    deskTheme: "infrastructure",
    personalityLine: "Three mugs deep. Notices the outage first.",
  },
  sage: {
    id: "sage",
    bodyType: "tall",
    headShape: "oval",
    skinTone: "s5",
    hair: "long-straight",
    hairTone: "h1",
    outfit: "long-coat",
    accessory: "glasses",
    palette: "teal",
    defaultPose: "seated_reviewing",
    deskTheme: "performance",
    personalityLine: "Patient with data. Impatient with conclusions.",
  },
  sentinel: {
    id: "sentinel",
    bodyType: "tall",
    headShape: "square",
    skinTone: "s1",
    hair: "flat-top",
    hairTone: "h2",
    outfit: "parka",
    accessory: "pager",
    palette: "ice",
    // Standing, like Nova and Milo, and for the same reason: the job is to be
    // looking at something. A seated Sentinel would read as a second Byte.
    defaultPose: "standing",
    deskTheme: "sentry",
    personalityLine: "Notices before anyone asks. Says the number, not the mood.",
  },
  patch: {
    id: "patch",
    bodyType: "broad",
    headShape: "oval",
    skinTone: "s3",
    hair: "shaggy",
    hairTone: "h3",
    outfit: "coveralls",
    accessory: "toolbox",
    palette: "rust",
    defaultPose: "seated_working",
    deskTheme: "reliability",
    personalityLine: "Finds the cause first. Fixes second, and only what is allowed.",
  },
  quinn: {
    id: "quinn",
    bodyType: "compact",
    headShape: "round",
    skinTone: "s4",
    hair: "braid",
    hairTone: "h4",
    outfit: "wrap-top",
    accessory: "checklist",
    palette: "mint",
    defaultPose: "seated_reviewing",
    deskTheme: "verification",
    personalityLine: "Takes nobody's word for it, including her own.",
  },
  karthik: {
    id: "karthik",
    // Compact and oval is an unused pairing — every other compact figure has a
    // round or square head — so the silhouette is already distinct before the
    // hair, jacket, headphones and six-screen bench are counted.
    bodyType: "compact",
    headShape: "oval",
    skinTone: "s3",
    hair: "undercut",
    hairTone: "h5",
    outfit: "track-jacket",
    accessory: "headphones",
    // Magenta: the one hue with nothing near it in the existing thirteen.
    // Crimson and rust are the closest and both sit well to the red side of
    // it, so the two never confuse at a glance.
    palette: "magenta",
    // Seated, deliberately. Four people already stand and a fifth would tip
    // the room from "a working floor" into "a meeting"; the job is also
    // genuinely a seated one — six screens and a keyboard.
    defaultPose: "seated_working",
    deskTheme: "wallet-ops",
    personalityLine: "Moves quickly inside a small remit, and says where its edge is.",
  },
};

/** The axes a reader can tell people apart by, with colour excluded. */
export const SHAPE_AXES = [
  "bodyType",
  "headShape",
  "hair",
  "outfit",
  "accessory",
  "defaultPose",
  "deskTheme",
] as const;

export type ShapeAxis = (typeof SHAPE_AXES)[number];

/**
 * How many shape axes two characters share.
 *
 * Used by the differentiation test. Colour is not counted: the requirement is
 * that they remain distinguishable with status colours disabled, so a check
 * that leaned on palette would pass while the thing it is meant to guarantee
 * quietly failed.
 */
export function sharedAxes(a: CharacterDefinition, b: CharacterDefinition): ShapeAxis[] {
  return SHAPE_AXES.filter((axis) => a[axis] === b[axis]);
}
