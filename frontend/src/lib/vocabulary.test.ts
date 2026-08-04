import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { AGENTS } from "@/lib/design/agents";

/**
 * The words the product is allowed to say.
 *
 * Sprint 28.2 finished a migration that had been half-done for several
 * sprints: the brand, the space theme, and a cast of codenamed agents. Each
 * removal was a one-line edit; the reason it kept coming back is that nothing
 * asserted it was gone.
 *
 * This walks the actual source rather than trusting a grep somebody ran once.
 * It is deliberately narrow — it bans *strings that reach a user*, not
 * identifiers. `AgentId`, `sentinel.tsx` and `--color-scout` are internal
 * names and may stay; "SENTINEL" rendered on a panel may not.
 */

const SRC = join(process.cwd(), "src");

/** Files whose contents a user can end up reading. */
function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

/**
 * Strings inside JSX text or quoted literals — what a user can see. Comments
 * are excluded: this codebase deliberately records *why* things changed, and
 * "SENTINEL was renamed" must remain writable in a comment.
 */
function userFacingText(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "") // block comments
    .replace(/^\s*\/\/.*$/gm, ""); // line comments
}

const FILES = sourceFiles(SRC);

describe("brand", () => {
  it("finds source files to check", () => {
    // A green test that checks nothing is worse than a red one.
    expect(FILES.length).toBeGreaterThan(30);
  });

  it("never says LETZMOON", () => {
    const offenders = FILES.filter((file) =>
      /LETZMOON/i.test(userFacingText(readFileSync(file, "utf8"))),
    );
    expect(offenders).toEqual([]);
  });
});

describe("space theme", () => {
  // Each of these was visible on a page before Sprint 28.2. `Observatory`
  // titled the token page's back link; `Mission report` and `Division
  // findings` headed a panel; `Commander` addressed the user.
  const BANNED = [
    "Observatory",
    "Commander",
    "Mission report",
    "Division findings",
    "Intelligence Division",
  ];

  for (const phrase of BANNED) {
    it(`never says "${phrase}"`, () => {
      const pattern = new RegExp(phrase, "i");
      const offenders = FILES.filter((file) =>
        pattern.test(userFacingText(readFileSync(file, "utf8"))),
      );
      expect(offenders).toEqual([]);
    });
  }
});

describe("analyst names", () => {
  it("names what each analyst measures, not a codename", () => {
    // A terminal names its dimensions. SCOUT, PULSE and SENTINEL were
    // characters, and a character implies a judgement the engine does not make.
    const names = Object.values(AGENTS).map((agent) => agent.name);
    const shouting = names.filter((name) => name === name.toUpperCase());
    expect(shouting).toEqual([]);
  });

  it("keeps every analyst distinctly named", () => {
    const names = Object.values(AGENTS).map((agent) => agent.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it("keeps the internal ids, which are not user-facing", () => {
    // The rename is a vocabulary change, not a refactor: hues, sigils and
    // pipeline order are keyed on these and must not move.
    expect(Object.keys(AGENTS)).toContain("sentinel");
    expect(Object.keys(AGENTS)).toContain("scout");
  });
});
