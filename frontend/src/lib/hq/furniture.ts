import type { Tile } from "./geometry";
import { ZONE_BY_ID } from "./zones";

/**
 * WHERE EVERY PIECE OF FURNITURE STANDS.
 *
 * One module, imported by three consumers that must never disagree: the stage
 * (which draws each piece), the ambient layer (which blocks walking through
 * them), and the tests (which assert nothing was placed on a desk, a route or
 * inside the vault). Before this file the placements lived in the stage
 * component and the blocked-tile list lived in `ambient.ts`, which worked only
 * as long as both were small — the world expansion triples the furniture, and
 * two hand-maintained lists describing the same room is how a character ends
 * up walking through a fridge.
 *
 * PLACEMENT RULES, ENFORCED BY TEST
 *
 * - Nothing stands on an operational desk, on a walk-route waypoint, or
 *   inside the Execution Vault.
 * - Everything non-sittable blocks walking. `sittable` marks the exceptions —
 *   chairs, sofas, benches, stools — which may be a route's *destination* but
 *   are still never walked through.
 * - Fractional coordinates mark purely visual placements set off the walk
 *   grid (a low table in front of a sofa). They cannot collide with a route
 *   because routes are authored on the integer grid.
 */

export interface Placement {
  kind: string;
  tile: Tile;
  /** A seat: walkable as a destination, drawn under whoever sits there. */
  sittable?: boolean;
}

/* ── the rooms ─────────────────────────────────────────────────────────── */

export const FURNITURE: Placement[] = [
  /* ---- Mission Control ------------------------------------------------ */
  { kind: "plant-large", tile: { col: 1, row: 1 } },
  // Col 4 row 0, not col 14. The Mission Board grew west-to-east across cols
  // ~9.6-14.7 in the composition pass, and this plant stood directly in front
  // of it — a shrub obscuring the one surface that speaks for the whole
  // office. Moved to the board's west, against the north wall: clear of the
  // board, clear of Nova at col 8, and off Radar's telescope route, which is
  // what col 5 row 1 turned out to be.
  { kind: "plant-large", tile: { col: 4, row: 0 } },

  /* ---- Risk Room ------------------------------------------------------ */
  { kind: "cabinet", tile: { col: 1, row: 2 } },
  { kind: "whiteboard", tile: { col: 3, row: 2 } },
  { kind: "bin", tile: { col: 1, row: 5 } },

  /* ---- Trading Floor -------------------------------------------------- */
  { kind: "plant-small", tile: { col: 5, row: 2 } },
  { kind: "bin", tile: { col: 5, row: 4 } },
  { kind: "bin", tile: { col: 11, row: 5 } },

  /* ---- Conference Room -------------------------------------------------
     The table is one drawing anchored on the middle tile but it occupies
     three; the two flanks are blocked via CONFERENCE_TABLE_TILES below. Six
     chairs, three a side. The head tiles at (17,2) and (21,2) stay clear —
     they are how a participant walks around to the south row. */
  { kind: "conference-table", tile: { col: 19, row: 2 } },
  { kind: "conf-chair", tile: { col: 18, row: 1 }, sittable: true },
  { kind: "conf-chair", tile: { col: 19, row: 1 }, sittable: true },
  { kind: "conf-chair", tile: { col: 20, row: 1 }, sittable: true },
  { kind: "conf-chair", tile: { col: 18, row: 3 }, sittable: true },
  { kind: "conf-chair", tile: { col: 19, row: 3 }, sittable: true },
  { kind: "conf-chair", tile: { col: 20, row: 3 }, sittable: true },
  { kind: "whiteboard", tile: { col: 21, row: 3 } },
  { kind: "plant-small", tile: { col: 17, row: 0 } },
  { kind: "plant-small", tile: { col: 21, row: 0 } },

  /* ---- Outdoor Break Deck ---------------------------------------------
     Exterior: benches, tables and planters — nothing that needs air.

     The deck now runs rows 4-11 rather than 4-7, because it absorbed the
     42-tile void that used to sit south-east of the building. Three props
     across eight rows read as an empty platform, so the southern half gets
     its own seating cluster: a second bench pair by the lounge door and a
     low table between them. Spread deliberately wide — this is the one
     space in HQ that is *supposed* to feel open, and filling it evenly
     would turn a terrace into a waiting room. */
  { kind: "bench", tile: { col: 18, row: 5 }, sittable: true },
  { kind: "bench", tile: { col: 20, row: 5 }, sittable: true },
  { kind: "standing-table", tile: { col: 19, row: 6 } },
  { kind: "plant-large", tile: { col: 21, row: 4 } },
  { kind: "lounge-chair", tile: { col: 17, row: 9 }, sittable: true },
  { kind: "lounge-chair", tile: { col: 19, row: 9 }, sittable: true },
  { kind: "low-table", tile: { col: 18, row: 10 } },
  { kind: "plant-large", tile: { col: 21, row: 8 } },
  { kind: "plant-small", tile: { col: 17, row: 11 } },
  { kind: "standing-table", tile: { col: 20, row: 11 } },

  /* ---- Portfolio ------------------------------------------------------ */
  { kind: "bookshelf", tile: { col: 0, row: 7 } },
  { kind: "cabinet", tile: { col: 3, row: 7 } },
  { kind: "plant-small", tile: { col: 0, row: 9 } },

  /* ---- Operations & Tech ---------------------------------------------- */
  { kind: "server-rack", tile: { col: 10, row: 8 } },
  { kind: "printer", tile: { col: 5, row: 9 } },
  { kind: "cabinet", tile: { col: 5, row: 7 } },
  { kind: "bin", tile: { col: 10, row: 9 } },

  /* ---- Performance Lab ------------------------------------------------ */
  { kind: "bookshelf", tile: { col: 11, row: 7 } },
  { kind: "bookshelf", tile: { col: 15, row: 8 } },
  { kind: "side-table", tile: { col: 14, row: 7 } },
  { kind: "plant-small", tile: { col: 11, row: 9 } },

  /* ---- Pantry -----------------------------------------------------------
     A kitchen run along the north wall of the room: fridge, counter with
     sink, counter with microwave, coffee machine, water cooler, snack shelf.
     Stools at the counter's south face. */
  { kind: "fridge", tile: { col: 0, row: 10 } },
  { kind: "counter-sink", tile: { col: 1, row: 10 } },
  { kind: "counter-micro", tile: { col: 2, row: 10 } },
  { kind: "coffee-machine", tile: { col: 3, row: 10 } },
  { kind: "water-cooler", tile: { col: 6, row: 10 } },
  { kind: "snack-shelf", tile: { col: 7, row: 10 } },
  { kind: "stool", tile: { col: 1, row: 11 }, sittable: true },
  { kind: "stool", tile: { col: 2, row: 11 }, sittable: true },
  { kind: "plant-large", tile: { col: 0, row: 11 } },

  /* ---- Lounge ----------------------------------------------------------
     Calmer than the pantry on purpose: a sofa, one reading chair, a low
     table set off the walk grid, the viewport, greenery. */
  { kind: "sofa", tile: { col: 9, row: 11 }, sittable: true },
  { kind: "lounge-chair", tile: { col: 11, row: 10 }, sittable: true },
  { kind: "low-table", tile: { col: 10.4, row: 11.5 } },
  // On the lounge's east side, where the floor meets the void the deck also
  // overlooks — a window into space reads as a window only when there is
  // space behind it.
  { kind: "viewport", tile: { col: 15, row: 10.5 } },
  { kind: "plant-large", tile: { col: 8, row: 10 } },
  { kind: "plant-small", tile: { col: 15, row: 11 } },

  /* ---- Facilities ------------------------------------------------------ */
  { kind: "supply-shelf", tile: { col: 0, row: 12 } },
  { kind: "box-stack", tile: { col: 0, row: 13 } },

  /* ---- Restrooms — signage and doors only, no interior ----------------- */
  { kind: "restroom-doors", tile: { col: 4, row: 12 } },

  /* ---- Reception -------------------------------------------------------
     Counter, brand stand, visitor chairs, the welcome board, a gate and the
     mat at the south edge where the way in reads as a way in. */
  { kind: "reception-counter", tile: { col: 9, row: 12 } },
  { kind: "logo-stand", tile: { col: 7, row: 12 } },
  { kind: "visitor-chair", tile: { col: 6, row: 13 }, sittable: true },
  { kind: "visitor-chair", tile: { col: 7, row: 13.4 }, sittable: true },
  { kind: "security-gate", tile: { col: 12, row: 13 } },
  { kind: "floor-mat", tile: { col: 10, row: 13.5 } },
  { kind: "cabinet", tile: { col: 14, row: 12 } },
  { kind: "plant-large", tile: { col: 15, row: 13 } },
];

/** The two flanking tiles of the three-tile conference table. */
export const CONFERENCE_TABLE_TILES: Tile[] = [
  { col: 18, row: 2 },
  { col: 19, row: 2 },
  { col: 20, row: 2 },
];

/**
 * Tiles occupied by the conference room's glass west wall. The doorway is the
 * row-1 tile; these two carry the glass and nobody walks through glass.
 */
export const GLASS_WALL_TILES: Tile[] = [
  { col: 16, row: 2 },
  { col: 16, row: 3 },
];

/** The vault's interior. Sealed to everyone — employees, support staff, cats. */
export const VAULT_TILES: Tile[] = (() => {
  const rect = ZONE_BY_ID.get("vault")!.rect;
  const tiles: Tile[] = [];
  for (let col = rect.col; col < rect.col + rect.cols; col += 1) {
    for (let row = rect.row; row < rect.row + rect.rows; row += 1) {
      tiles.push({ col, row });
    }
  }
  return tiles;
})();

/**
 * Every tile walking must respect, beyond desks and the back wall.
 *
 * Sittable furniture is deliberately absent: a chair is a destination, not an
 * obstacle. Fractional placements are absent too — they sit off the walk grid
 * by construction.
 */
export const FURNITURE_BLOCKED: Tile[] = [
  ...FURNITURE.filter(
    (piece) =>
      !piece.sittable &&
      Number.isInteger(piece.tile.col) &&
      Number.isInteger(piece.tile.row),
  ).map((piece) => piece.tile),
  ...CONFERENCE_TABLE_TILES,
  ...GLASS_WALL_TILES,
  ...VAULT_TILES,
];

/* ── rugs ──────────────────────────────────────────────────────────────── */

export interface RugSpec {
  col: number;
  row: number;
  cols: number;
  rows: number;
  warm?: boolean;
}

export const RUGS: RugSpec[] = [
  { col: 5.3, row: 2.2, cols: 7.4, rows: 3.6 },
  // On the lounge's floorboards, warm rather than blue.
  { col: 8.8, row: 10.3, cols: 5.4, rows: 1.5, warm: true },
];

/* ── the seats people and cats actually use ────────────────────────────── */

/** Where a lounging employee sits on the sofa. Off-grid, on the cushion. */
export const SOFA_SEAT: Tile = { col: 9.25, row: 11.05 };
/** The reading chair's cushion. */
export const LOUNGE_CHAIR_SEAT: Tile = { col: 11, row: 10 };
/** The deck benches. */
export const BENCH_SEATS: Tile[] = [
  { col: 18, row: 5 },
  { col: 20, row: 5 },
];

/**
 * The conference seats, in the order meetings fill them.
 *
 * North row first (walked to along the row-1 corridor), then the south row
 * (walked around the table's west end). Every meeting cast is 4 or fewer, so
 * the south row is rarely full — which also keeps the average walk shorter.
 */
export const CONFERENCE_SEATS: Tile[] = [
  { col: 18, row: 1 },
  { col: 19, row: 1 },
  { col: 20, row: 1 },
  { col: 18, row: 3 },
  { col: 19, row: 3 },
  { col: 20, row: 3 },
];
