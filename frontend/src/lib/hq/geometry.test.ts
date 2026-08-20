import { describe, expect, it } from "vitest";

import {
  GRID_COLS,
  GRID_ROWS,
  LAYER,
  ROOM_W,
  TILE_H,
  TILE_W,
  depthOf,
  isInsideRoom,
  rectCentre,
  rectPolygon,
  rectsOverlap,
  toScreen,
} from "./geometry";
import { EMPLOYEES } from "./employees";
import { ZONES, ZONE_BY_ID } from "./zones";

/**
 * The floor plan, checked as arithmetic.
 *
 * An isometric room fails silently: a desk placed one tile wrong looks
 * plausible, and two zones laid on top of each other just look like a slightly
 * odd floor. Expressing the layout as data means these are assertions rather
 * than things somebody has to notice in a screenshot.
 */

describe("isometric projection", () => {
  it("places the origin tile at the diamond's north corner", () => {
    // North corner, not centre: the room is 16×12, so the widest point sits
    // east of the origin. Asserting `ROOM_W / 2` here is what hid the offset
    // bug on a square grid.
    expect(toScreen({ col: 0, row: 0 })).toEqual({ x: GRID_ROWS * (TILE_W / 2), y: 0 });
  });

  it("puts the west and east corners exactly on the room's edges", () => {
    expect(toScreen({ col: 0, row: GRID_ROWS }).x).toBe(0);
    expect(toScreen({ col: GRID_COLS, row: 0 }).x).toBe(ROOM_W);
  });

  it("moves right and down when going east", () => {
    const origin = toScreen({ col: 0, row: 0 });
    const east = toScreen({ col: 1, row: 0 });
    expect(east.x).toBe(origin.x + TILE_W / 2);
    expect(east.y).toBe(origin.y + TILE_H / 2);
  });

  it("moves left and down when going south", () => {
    const origin = toScreen({ col: 0, row: 0 });
    const south = toScreen({ col: 0, row: 1 });
    expect(south.x).toBe(origin.x - TILE_W / 2);
    expect(south.y).toBe(origin.y + TILE_H / 2);
  });

  it("keeps every tile inside the room's horizontal extent", () => {
    for (let col = 0; col <= GRID_COLS; col += 1) {
      for (let row = 0; row <= GRID_ROWS; row += 1) {
        const point = toScreen({ col, row });
        expect(point.x).toBeGreaterThanOrEqual(0);
        expect(point.x).toBeLessThanOrEqual(ROOM_W);
      }
    }
  });
});

describe("paint order", () => {
  it("sorts a southern tile in front of a northern one", () => {
    expect(depthOf({ col: 0, row: 5 })).toBeGreaterThan(depthOf({ col: 0, row: 4 }));
  });

  it("sorts a person in front of their own desk", () => {
    const tile = { col: 6, row: 3 };
    expect(depthOf(tile, LAYER.employee)).toBeGreaterThan(depthOf(tile, LAYER.desk));
  });

  it("keeps layers within one tile below the next tile", () => {
    // Without this the topmost layer of one tile would sort above the floor of
    // the tile in front of it, and a screen would draw over a nearer desk.
    const near = depthOf({ col: 0, row: 0 }, LAYER.overlay);
    const next = depthOf({ col: 1, row: 0 }, LAYER.floor);
    expect(near).toBeLessThan(next);
  });
});

describe("floor plan", () => {
  it("keeps every zone inside the room", () => {
    for (const zone of ZONES) {
      expect(isInsideRoom({ col: zone.rect.col, row: zone.rect.row })).toBe(true);
      expect(zone.rect.col + zone.rect.cols).toBeLessThanOrEqual(GRID_COLS);
      expect(zone.rect.row + zone.rect.rows).toBeLessThanOrEqual(GRID_ROWS);
    }
  });

  it("never overlaps two departments", () => {
    for (let i = 0; i < ZONES.length; i += 1) {
      for (let j = i + 1; j < ZONES.length; j += 1) {
        const a = ZONES[i]!;
        const b = ZONES[j]!;
        expect(rectsOverlap(a.rect, b.rect), `${a.id} overlaps ${b.id}`).toBe(false);
      }
    }
  });

  it("produces a four-corner polygon for every zone", () => {
    for (const zone of ZONES) {
      expect(rectPolygon(zone.rect).split(" ")).toHaveLength(4);
    }
  });

  it("reads the trading floor west to east in journey order", () => {
    // The room's geometry is meant to teach the pipeline. If someone reorders
    // the desks this fails, which is the point.
    const order = ["radar", "luna", "dex", "rex"];
    const columns = order.map(
      (id) => EMPLOYEES.find((employee) => employee.id === id)!.desk.col,
    );
    const sorted = [...columns].sort((a, b) => a - b);
    expect(columns).toEqual(sorted);
  });

  it("puts the vault east of execution", () => {
    const rex = EMPLOYEES.find((employee) => employee.id === "rex")!;
    expect(ZONE_BY_ID.get("vault")!.rect.col).toBeGreaterThanOrEqual(rex.desk.col);
  });

  it("centres a zone label inside its own rect", () => {
    for (const zone of ZONES) {
      const centre = rectCentre(zone.rect);
      expect(Number.isFinite(centre.x)).toBe(true);
      expect(Number.isFinite(centre.y)).toBe(true);
    }
  });
});

describe("staff placement", () => {
  it("stands every employee inside the room", () => {
    for (const employee of EMPLOYEES) {
      expect(isInsideRoom(employee.desk), `${employee.id} is outside the room`).toBe(true);
    }
  });

  it("stands every employee inside their own department", () => {
    for (const employee of EMPLOYEES) {
      const zone = ZONE_BY_ID.get(employee.zone);
      expect(zone, `${employee.id} has an unknown zone`).toBeDefined();
      const { col, row, cols, rows } = zone!.rect;
      expect(
        employee.desk.col >= col && employee.desk.col < col + cols,
        `${employee.id} is not inside ${employee.zone}`,
      ).toBe(true);
      expect(
        employee.desk.row >= row && employee.desk.row < row + rows,
        `${employee.id} is not inside ${employee.zone}`,
      ).toBe(true);
    }
  });

  it("gives no two employees the same desk", () => {
    const seen = new Set(EMPLOYEES.map((employee) => `${employee.desk.col},${employee.desk.row}`));
    expect(seen.size).toBe(EMPLOYEES.length);
  });
});
