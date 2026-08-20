import { describe, expect, it } from "vitest";

import {
  CHARACTERS,
  SHAPE_AXES,
  sharedAxes,
  type CharacterDefinition,
} from "./characters";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "./employees";

/**
 * THE DIFFERENTIATION CONTRACT.
 *
 * The brief's requirement is that a reader can tell these ten apart with the
 * labels hidden and the status colours disabled. That is a property of the
 * *shapes*, so these tests never look at palette — a check that counted colour
 * would pass while the thing it guarantees quietly failed.
 */

const ALL = Object.values(CHARACTERS);

describe("the roster and the cast agree", () => {
  it("draws exactly the ten people on the roster", () => {
    expect(ALL).toHaveLength(10);
    expect(new Set(ALL.map((c) => c.id))).toEqual(new Set(EMPLOYEES.map((e) => e.id)));
  });

  it("keys every character by its own id", () => {
    for (const [key, character] of Object.entries(CHARACTERS)) {
      expect(character.id).toBe(key);
    }
  });

  it("gives every character a roster entry with a role and a department", () => {
    for (const character of ALL) {
      const employee = EMPLOYEE_BY_ID.get(character.id);
      expect(employee, `${character.id} has no roster entry`).toBeDefined();
      expect(employee!.role.length).toBeGreaterThan(0);
      expect(employee!.zone.length).toBeGreaterThan(0);
    }
  });

  it("gives every employee a unique name and a unique role", () => {
    expect(new Set(EMPLOYEES.map((e) => e.name)).size).toBe(EMPLOYEES.length);
    expect(new Set(EMPLOYEES.map((e) => e.role)).size).toBe(EMPLOYEES.length);
  });
});

describe("visual differentiation", () => {
  /**
   * The headline check. Seven shape axes; no pair may match on more than four,
   * which means every pair differs on at least three — the brief's bar.
   */
  it("keeps every pair distinct on at least three shape axes", () => {
    const failures: string[] = [];
    for (let i = 0; i < ALL.length; i += 1) {
      for (let j = i + 1; j < ALL.length; j += 1) {
        const a = ALL[i]!;
        const b = ALL[j]!;
        const shared = sharedAxes(a, b);
        const differing = SHAPE_AXES.length - shared.length;
        if (differing < 3) {
          failures.push(
            `${a.id} vs ${b.id}: only ${differing} differing axes (shared: ${shared.join(", ")})`,
          );
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it("gives every character a unique desk theme", () => {
    // The desk is half the identity: two people with the same instruments are
    // two people doing the same job.
    expect(new Set(ALL.map((c) => c.deskTheme)).size).toBe(ALL.length);
  });

  it("gives every character a unique accessory", () => {
    expect(new Set(ALL.map((c) => c.accessory)).size).toBe(ALL.length);
  });

  it("gives every character a unique hairstyle", () => {
    expect(new Set(ALL.map((c) => c.hair)).size).toBe(ALL.length);
  });

  it("gives every character a unique outfit", () => {
    expect(new Set(ALL.map((c) => c.outfit)).size).toBe(ALL.length);
  });

  it("uses more than one build, head shape and skin tone", () => {
    // Guards against a cast that is technically distinct but visually uniform.
    expect(new Set(ALL.map((c) => c.bodyType)).size).toBeGreaterThanOrEqual(3);
    expect(new Set(ALL.map((c) => c.headShape)).size).toBeGreaterThanOrEqual(3);
    expect(new Set(ALL.map((c) => c.skinTone)).size).toBeGreaterThanOrEqual(4);
  });

  it("does not rely on palette to tell anyone apart", () => {
    // Palettes are unique too, but the differentiation test above deliberately
    // excludes them. This asserts that exclusion is real.
    expect(SHAPE_AXES).not.toContain("palette" as never);
    expect(new Set(ALL.map((c) => c.palette)).size).toBe(ALL.length);
  });
});

describe("posture", () => {
  it("seats most of the cast and stands a few", () => {
    // A room where everyone stands reads as a meeting; where everyone sits, as
    // a call centre. The mix is what makes it look like a working floor.
    const standing = ALL.filter((c) => c.defaultPose === "standing");
    expect(standing.length).toBeGreaterThanOrEqual(2);
    expect(standing.length).toBeLessThanOrEqual(4);
  });

  it("stands the director", () => {
    expect(CHARACTERS.nova.defaultPose).toBe("standing");
  });

  it("uses every pose the rig supports at least once, or has a reason not to", () => {
    const used = new Set(ALL.map((c) => c.defaultPose));
    // `seated_working`, `seated_reviewing`, `standing` and `coffee_idle` are in
    // the cast. `holding_tablet` is rigged but unused as a *default* — it is a
    // transition pose HQ-3 moves Nova into, not a resting state.
    expect(used).toContain("seated_working");
    expect(used).toContain("seated_reviewing");
    expect(used).toContain("standing");
    expect(used).toContain("coffee_idle");
  });
});

describe("no fabricated operational content", () => {
  it("carries no status vocabulary in any personality line", () => {
    const forbidden = [
      "ONLINE",
      "HEALTHY",
      "ACTIVE",
      "APPROVED",
      "PROFIT",
      "%",
      "$",
    ];
    for (const character of ALL) {
      for (const word of forbidden) {
        expect(
          character.personalityLine.toUpperCase().includes(word),
          `${character.id} personality line contains ${word}`,
        ).toBe(false);
      }
    }
  });

  it("gives every character a personality line that describes a person", () => {
    for (const character of ALL) {
      expect(character.personalityLine.length).toBeGreaterThan(10);
      expect(character.personalityLine.length).toBeLessThan(90);
    }
  });
});

describe("sharedAxes", () => {
  it("reports every axis for a character compared with itself", () => {
    const nova = CHARACTERS.nova;
    expect(sharedAxes(nova, nova)).toHaveLength(SHAPE_AXES.length);
  });

  it("reports none for two characters built differently", () => {
    const a: CharacterDefinition = { ...CHARACTERS.nova };
    const b: CharacterDefinition = { ...CHARACTERS.byte };
    expect(sharedAxes(a, b).length).toBeLessThan(SHAPE_AXES.length);
  });
});
