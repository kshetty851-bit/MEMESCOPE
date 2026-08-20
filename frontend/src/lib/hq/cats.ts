import type { ActorFrame } from "./ambient";
import type { Tile } from "./geometry";

/**
 * THE OFFICE CATS.
 *
 * Cosmo and Mochi are permanent residents of HQ and the least operational
 * things in it. They do not appear in `deriveHqState`, they cannot influence a
 * reading, and nothing they do can ever touch a control — not because the
 * cats are well trained but because there is no code path from a cat to
 * anything: their frames drive SVG transforms and a personality panel, and
 * that is the entire surface. A test walks their vocabulary the same way it
 * walks the humans', so no cat can ever appear to have submitted a trade.
 *
 * THEIR MOVEMENT MODEL
 *
 * Cats do not walk the tile grid; they slink between authored fractional
 * waypoints, which is what lets them settle *beside* things — a desk leg, a
 * sofa arm — where a grid walker could only stand on top of the tile. The
 * safety rules are theirs alone and tested: never inside the vault, never
 * through the conference glass, never closer than half a tile to an
 * operational desk anchor, and steps short enough that the slide between
 * waypoints reads as an animal moving rather than a token teleporting.
 */

export type CatId = "cosmo" | "mochi";

export type CatPose =
  | "cat_walk"
  | "cat_sit"
  | "cat_sleep"
  | "cat_stretch"
  | "cat_groom"
  | "cat_watch"
  | "cat_pounce";

export interface CatFrame extends ActorFrame {
  pose: CatPose;
}

export interface CatRoutine {
  id: string;
  actor: CatId;
  weight: number;
  frames: CatFrame[];
  /** Employees who play along — the petting and shooing interactions. */
  cast?: Array<{ actor: string; frames: ActorFrame[] }>;
  suppressOnAlert?: boolean;
  nightFactor?: number;
}

export interface Cat {
  id: CatId;
  name: string;
  /** The joke title on the personality panel. Never an operational word. */
  title: string;
  /** Coat palette key, resolved in `hq.css`. */
  coat: "black" | "cream";
  home: Tile;
  restingDetail: string;
  /** What they do at home when nothing is scheduled. */
  restingPose: CatPose;
}

export const CATS: Cat[] = [
  {
    id: "cosmo",
    name: "Cosmo",
    title: "Chief Distraction Officer",
    coat: "black",
    home: { col: 10.5, row: 8.8 },
    restingDetail: "Loitering by the server rack.",
    restingPose: "cat_sit",
  },
  {
    id: "mochi",
    name: "Mochi",
    title: "Chief Nap Officer",
    coat: "cream",
    home: { col: 9.7, row: 10.85 },
    restingDetail: "Occupying the good end of the sofa.",
    restingPose: "cat_sleep",
  },
];

export const CAT_BY_ID = new Map(CATS.map((cat) => [cat.id, cat]));
export const CAT_IDS = CATS.map((cat) => cat.id);

/** How long one cat step holds. Quicker than a person; cats flow. */
export const CAT_STEP_MS = 1_500;

function slink(tiles: Tile[]): CatFrame[] {
  return tiles.map((tile) => ({ pose: "cat_walk", tile, hold: CAT_STEP_MS }));
}

function slinkHome(tiles: Tile[]): CatFrame[] {
  return [
    ...slink([...tiles].reverse()),
    { pose: "cat_walk", hold: CAT_STEP_MS },
  ];
}

/* ── the routes ───────────────────────────────────────────────────────── */

const COSMO_TO_MISSION: Tile[] = [
  { col: 10.4, row: 7.7 },
  { col: 10, row: 6.6 },
  { col: 9.6, row: 5.6 },
  { col: 9.5, row: 4.5 },
  { col: 9.4, row: 3.5 },
  { col: 9.4, row: 2.6 },
];

const COSMO_TO_VIEWPORT: Tile[] = [
  { col: 11.2, row: 9.4 },
  { col: 12.1, row: 10 },
  { col: 13.2, row: 10.5 },
  { col: 14.3, row: 10.9 },
];

const COSMO_TO_RECEPTION: Tile[] = [
  { col: 10.6, row: 9.8 },
  { col: 10.4, row: 10.9 },
  { col: 10.2, row: 12.1 },
  { col: 10, row: 13.2 },
];

const COSMO_TO_REX: Tile[] = [
  { col: 10.6, row: 7.7 },
  { col: 11.2, row: 6.8 },
  { col: 11.8, row: 5.8 },
  { col: 12.4, row: 5 },
  { col: 12.6, row: 4.7 },
];

const MOCHI_TO_SAGE: Tile[] = [
  { col: 10.6, row: 10.6 },
  { col: 11.5, row: 10.9 },
  { col: 12.3, row: 10.4 },
  { col: 13.1, row: 9.6 },
  { col: 13.4, row: 8.7 },
];

const MOCHI_TO_PANTRY: Tile[] = [
  { col: 8.8, row: 11.3 },
  { col: 7.8, row: 11.2 },
  { col: 6.7, row: 11.2 },
  { col: 5.5, row: 11.2 },
];

const MOCHI_TO_WINDOW: Tile[] = [
  { col: 10.7, row: 10.9 },
  { col: 11.8, row: 10.8 },
  { col: 12.9, row: 10.9 },
  { col: 14, row: 11 },
];

export const CAT_ROUTINES: CatRoutine[] = [
  /* ---- Cosmo: curious, moves often ------------------------------------- */
  {
    id: "cosmo-cables",
    actor: "cosmo",
    weight: 3,
    nightFactor: 0.7,
    frames: [
      ...slink([{ col: 9.9, row: 8.55 }]),
      { pose: "cat_watch", tile: { col: 9.9, row: 8.55 }, hold: 8_000, detail: "Inspecting Byte's cables." },
      { pose: "cat_groom", tile: { col: 9.9, row: 8.55 }, hold: 6_000, detail: "Grooming, next to the cable spill." },
      ...slinkHome([{ col: 9.9, row: 8.55 }]),
    ],
  },
  {
    id: "cosmo-screens",
    actor: "cosmo",
    weight: 2,
    nightFactor: 0.7,
    frames: [
      ...slink(COSMO_TO_MISSION),
      { pose: "cat_watch", tile: { col: 9.4, row: 2.6 }, hold: 9_000, detail: "Watching the moving charts." },
      ...slinkHome(COSMO_TO_MISSION),
    ],
  },
  {
    id: "cosmo-viewport",
    actor: "cosmo",
    weight: 2,
    frames: [
      ...slink(COSMO_TO_VIEWPORT),
      { pose: "cat_watch", tile: { col: 14.3, row: 10.9 }, hold: 8_000, detail: "Watching for spacecraft." },
      { pose: "cat_stretch", tile: { col: 14.3, row: 10.9 }, hold: 3_000, detail: "A long stretch by the viewport." },
      ...slinkHome(COSMO_TO_VIEWPORT),
    ],
  },
  {
    id: "cosmo-reception",
    actor: "cosmo",
    weight: 1.5,
    nightFactor: 0.5,
    frames: [
      ...slink(COSMO_TO_RECEPTION),
      { pose: "cat_sit", tile: { col: 10, row: 13.2 }, hold: 10_000, detail: "Guarding the front mat." },
      ...slinkHome(COSMO_TO_RECEPTION),
    ],
  },
  {
    // Rex's desk is the Paper desk, and the cat is not allowed on it. The
    // shooing is a gesture and a retreat — nothing here touches a control,
    // and the panel line says so in cat terms, not trading terms.
    id: "cosmo-rex",
    actor: "cosmo",
    weight: 0.8,
    suppressOnAlert: true,
    frames: [
      ...slink(COSMO_TO_REX),
      { pose: "cat_sit", tile: { col: 12.6, row: 4.7 }, hold: 5_000, detail: "Sitting much too close to Rex's desk." },
      { pose: "cat_walk", tile: { col: 12.4, row: 5 }, hold: 2_500, detail: "Escorted away from the Paper desk, again." },
      ...slinkHome(COSMO_TO_REX.slice(0, -1)),
    ],
    cast: [
      {
        actor: "rex",
        frames: [
          { pose: "seated_working", hold: CAT_STEP_MS * 5 },
          { pose: "talking_briefly", hold: 5_000, detail: "Gently relocating Cosmo." },
          { pose: "seated_working", hold: 2_500 },
        ],
      },
    ],
  },
  {
    id: "cosmo-byte",
    actor: "cosmo",
    weight: 1,
    frames: [
      ...slink([{ col: 9.9, row: 8.55 }]),
      { pose: "cat_sit", tile: { col: 9.9, row: 8.55 }, hold: 9_000, detail: "Sitting beside Byte's keyboard." },
      ...slinkHome([{ col: 9.9, row: 8.55 }]),
    ],
    cast: [
      {
        actor: "byte",
        frames: [
          { pose: "seated_working", hold: CAT_STEP_MS },
          { pose: "talking_briefly", hold: 4_500, detail: "Saying hello to Cosmo." },
          { pose: "seated_working", hold: 4_500 },
        ],
      },
    ],
  },
  {
    // The chase. Suppressed on alert — a crisis room does not need slapstick —
    // and the pounce is the only quick movement any cat makes.
    id: "cats-chase",
    actor: "cosmo",
    weight: 0.8,
    suppressOnAlert: true,
    nightFactor: 0.3,
    frames: [
      ...slink([
        { col: 9.9, row: 10.2 },
        { col: 9, row: 9.6 },
        { col: 8.2, row: 9.3 },
      ]),
      { pose: "cat_pounce", tile: { col: 7.4, row: 9.6 }, hold: 2_200, detail: "Chasing Mochi around the lounge." },
      { pose: "cat_sit", tile: { col: 7.4, row: 9.6 }, hold: 4_000, detail: "Pretending that was dignified." },
      ...slinkHome([
        { col: 9.9, row: 10.2 },
        { col: 9, row: 9.6 },
        { col: 8.2, row: 9.3 },
        { col: 7.4, row: 9.6 },
      ]),
    ],
    cast: [
      {
        actor: "mochi",
        frames: [
          { pose: "cat_walk", tile: { col: 9.4, row: 10.2 }, hold: CAT_STEP_MS, detail: "Being chased, tolerantly." },
          { pose: "cat_walk", tile: { col: 8.6, row: 9.7 }, hold: CAT_STEP_MS, detail: "Being chased, tolerantly." },
          { pose: "cat_pounce", tile: { col: 7.9, row: 9.9 }, hold: 2_200, detail: "Being chased, tolerantly." },
          { pose: "cat_sit", tile: { col: 7.9, row: 9.9 }, hold: 4_500, detail: "Declaring the game over." },
          { pose: "cat_walk", tile: { col: 8.6, row: 9.7 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", tile: { col: 9.4, row: 10.2 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", hold: CAT_STEP_MS },
        ],
      },
    ],
  },

  /* ---- Mochi: sleepy, moves rarely -------------------------------------- */
  {
    id: "mochi-sleep",
    actor: "mochi",
    weight: 4,
    nightFactor: 1.4,
    frames: [
      { pose: "cat_sleep", hold: 26_000, detail: "Asleep on the lounge sofa." },
      { pose: "cat_stretch", hold: 3_000, detail: "The waking-up stretch." },
      { pose: "cat_sleep", hold: 12_000, detail: "Asleep again immediately." },
    ],
  },
  {
    id: "mochi-sage",
    actor: "mochi",
    weight: 1.5,
    frames: [
      ...slink(MOCHI_TO_SAGE),
      { pose: "cat_sit", tile: { col: 13.4, row: 8.7 }, hold: 10_000, detail: "Sitting with Sage." },
      { pose: "cat_groom", tile: { col: 13.4, row: 8.7 }, hold: 5_000, detail: "Grooming, beside Sage's chair." },
      ...slinkHome(MOCHI_TO_SAGE),
    ],
    cast: [
      {
        actor: "sage",
        frames: [
          { pose: "seated_reviewing", hold: CAT_STEP_MS * 5 },
          { pose: "talking_briefly", hold: 4_000, detail: "Petting Mochi." },
          { pose: "seated_reviewing", hold: 4_000 },
        ],
      },
    ],
  },
  {
    id: "mochi-rug",
    actor: "mochi",
    weight: 2,
    nightFactor: 1.2,
    frames: [
      ...slink([
        { col: 10.5, row: 11.1 },
        { col: 11.3, row: 11.2 },
      ]),
      { pose: "cat_sleep", tile: { col: 11.3, row: 11.2 }, hold: 18_000, detail: "Napping on the warm rug." },
      ...slinkHome([
        { col: 10.5, row: 11.1 },
        { col: 11.3, row: 11.2 },
      ]),
    ],
  },
  {
    id: "mochi-pantry",
    actor: "mochi",
    weight: 1,
    nightFactor: 0.4,
    frames: [
      ...slink(MOCHI_TO_PANTRY),
      { pose: "cat_sit", tile: { col: 5.5, row: 11.2 }, hold: 8_000, detail: "Supervising the snack shelf." },
      ...slinkHome(MOCHI_TO_PANTRY),
    ],
  },
  {
    id: "mochi-window",
    actor: "mochi",
    weight: 1,
    frames: [
      ...slink(MOCHI_TO_WINDOW),
      { pose: "cat_watch", tile: { col: 14, row: 11 }, hold: 9_000, detail: "Watching the stars, half asleep." },
      ...slinkHome(MOCHI_TO_WINDOW),
    ],
  },
  {
    // Both cats at the viewport for a passing craft. The rarest routine in
    // the file, which is what makes catching it feel like something.
    id: "cats-viewport",
    actor: "cosmo",
    weight: 0.5,
    frames: [
      ...slink([
        { col: 11.2, row: 9.4 },
        { col: 12.3, row: 10.2 },
        { col: 13.4, row: 10.8 },
        { col: 14.2, row: 11.1 },
      ]),
      { pose: "cat_watch", tile: { col: 14.2, row: 11.1 }, hold: 10_000, detail: "Both watching something cross the window." },
      ...slinkHome([
        { col: 11.2, row: 9.4 },
        { col: 12.3, row: 10.2 },
        { col: 13.4, row: 10.8 },
        { col: 14.2, row: 11.1 },
      ]),
    ],
    cast: [
      {
        actor: "mochi",
        frames: [
          { pose: "cat_walk", tile: { col: 10.8, row: 10.9 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", tile: { col: 12, row: 10.8 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", tile: { col: 13.2, row: 10.9 }, hold: CAT_STEP_MS },
          { pose: "cat_watch", tile: { col: 13.6, row: 11.3 }, hold: 10_000, detail: "Both watching something cross the window." },
          { pose: "cat_walk", tile: { col: 13.2, row: 10.9 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", tile: { col: 12, row: 10.8 }, hold: CAT_STEP_MS },
          { pose: "cat_walk", hold: CAT_STEP_MS },
        ],
      },
    ],
  },
];

/**
 * THE THREE THINGS THE CATS DID NOT DO YET.
 *
 * Getting petted, going to the lounge, and noticing that a stranger is in the
 * building. All three are the same machinery as everything above — a timeline
 * of poses at fractional waypoints, optionally with somebody playing along.
 *
 * The petting routine is the one worth a note: it casts an *employee*, which
 * is the only direction that interaction can safely run. A cat cannot make
 * anybody do anything, and a routine that started from the human's side would
 * be an ambient routine claiming a person left their desk because of a cat.
 * Here the cat arrives and the human reacts, which is also how it works.
 */
CAT_ROUTINES.push(
  {
    id: "mochi-petted",
    actor: "mochi",
    weight: 0.9,
    suppressOnAlert: true,
    frames: [
      ...slink([
        { col: 10.3, row: 10.2 },
        { col: 10.6, row: 9.3 },
        { col: 10.2, row: 8.8 },
        { col: 9.9, row: 8.6 },
      ]),
      { pose: "cat_sit", tile: { col: 9.9, row: 8.6 }, hold: 4_200, detail: "Being scratched behind the ears." },
      { pose: "cat_groom", tile: { col: 9.9, row: 8.6 }, hold: 3_400, detail: "Thoroughly pleased with herself." },
      ...slinkHome([
        { col: 10.3, row: 10.2 },
        { col: 10.6, row: 9.3 },
        { col: 10.2, row: 8.8 },
      ]),
    ],
    cast: [
      {
        actor: "byte",
        frames: [
          { pose: "seated_working", hold: CAT_STEP_MS * 3 },
          { pose: "talking_briefly", hold: 4_200, detail: "Petting Mochi instead of working." },
          { pose: "seated_working", hold: 3_400 },
        ],
      },
    ],
  },
  {
    id: "cosmo-lounge",
    actor: "cosmo",
    weight: 1,
    frames: [
      ...slink([
        { col: 10.7, row: 9.7 },
        { col: 11.2, row: 10.5 },
        { col: 11.8, row: 10.9 },
      ]),
      { pose: "cat_stretch", tile: { col: 11.8, row: 10.9 }, hold: 3_000, detail: "A full-length stretch on the lounge rug." },
      { pose: "cat_sleep", tile: { col: 11.8, row: 10.9 }, hold: 11_000, detail: "Asleep on the lounge rug." },
      ...slinkHome([
        { col: 10.7, row: 9.7 },
        { col: 11.2, row: 10.5 },
      ]),
    ],
  },
  {
    // The cats notice a stranger before anybody else does. Cosmetic, and
    // deliberately not coordinated with the visitor system: a cat that only
    // ever appeared when a guest did would be a tell rather than a cat.
    id: "cosmo-stranger",
    actor: "cosmo",
    weight: 0.7,
    nightFactor: 0.2,
    frames: [
      ...slink([
        { col: 10.5, row: 9.9 },
        { col: 10.6, row: 10.9 },
        { col: 10.4, row: 11.4 },
      ]),
      { pose: "cat_watch", tile: { col: 10.4, row: 11.4 }, hold: 6_400, detail: "Watching the front door with deep suspicion." },
      { pose: "cat_sit", tile: { col: 10.4, row: 11.4 }, hold: 4_000, detail: "Supervising Reception." },
      ...slinkHome([
        { col: 10.5, row: 9.9 },
        { col: 10.6, row: 10.9 },
      ]),
    ],
  },
);

export const CAT_ROUTINES_BY_ACTOR = new Map<CatId, CatRoutine[]>(
  CAT_IDS.map((id) => [id, CAT_ROUTINES.filter((routine) => routine.actor === id)]),
);
