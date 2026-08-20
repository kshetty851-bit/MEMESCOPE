import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Portrait } from "@/components/hq/portrait";
import { CHARACTERS } from "@/lib/hq/characters";
import { EMPLOYEES } from "@/lib/hq/employees";

/**
 * Homepage portraits must BE the HQ characters — one source, no second cast.
 *
 * Identity in this rig is data: `CHARACTERS[id]` names a skin tone, hair tone
 * and garment palette, and the `Character` component writes them onto the
 * figure group as custom properties which `characters.css` resolves. The crew
 * section renders the same `Portrait` component over the same data, so the
 * only ways homepage and HQ could drift apart are:
 *
 *   1. the crew growing its own artwork instead of the rig,
 *   2. a second palette definition shadowing `characters.css`,
 *   3. the palette going back to being scoped where the homepage cannot see
 *      it — which is precisely how ten correct characters once rendered as
 *      ten black silhouettes.
 *
 * Each test below closes one of those doors.
 */

const SRC = join(process.cwd(), "src");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");
const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

describe("one cast, one source", () => {
  it("derives every homepage portrait from CHARACTERS, per person", () => {
    for (const employee of EMPLOYEES) {
      const spec = CHARACTERS[employee.id];
      const { container, unmount } = render(<Portrait id={employee.id} frame="bust" />);
      const figure = container.querySelector(".hq-character") as HTMLElement;
      expect(figure, `${employee.id} has no rig figure`).not.toBeNull();
      // The figure's colours are references into the shared palette, spelled
      // from the character definition — not literals that could be edited on
      // one surface and not the other.
      expect(figure.style.getPropertyValue("--hq-skin")).toBe(
        `var(--hq-skin-${spec.skinTone})`,
      );
      expect(figure.style.getPropertyValue("--hq-hair")).toBe(
        `var(--hq-hair-${spec.hairTone})`,
      );
      expect(figure.style.getPropertyValue("--hq-garment")).toBe(
        `var(--hq-${spec.palette})`,
      );
      unmount();
    }
  });

  it("keeps the crew section free of any artwork of its own", () => {
    const crew = read("components/alpha/crew.tsx");
    // The crew may only *mount* the rig. The moment it draws a path or embeds
    // an image it has become a second cast that can drift.
    expect(crew).toContain('from "@/components/hq/portrait"');
    expect(crew).not.toMatch(/<path/i);
    expect(crew).not.toMatch(/<img/i);
    expect(crew).not.toMatch(/url\(/);
  });

  it("ships the palette with the rig itself", () => {
    // The rig imports its own stylesheet, so every surface that renders a
    // character gets the colours by construction — a surface cannot mount the
    // cast and forget to dress it.
    const rig = read("components/hq/character-rig.tsx");
    expect(rig).toContain('import "@/styles/characters.css"');
  });

  it("scopes the palette where every surface can resolve it", () => {
    const css = stripComments(read("styles/characters.css"));
    // Tokens on :root, not under .hq. Scoping them to the HQ page is the
    // regression this whole suite exists for.
    const rootBlock = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
    for (const token of [
      "--hq-skin-s1:", "--hq-skin-s5:",
      "--hq-hair-h1:", "--hq-hair-h5:",
      "--hq-indigo:", "--hq-cyan:", "--hq-violet:", "--hq-amber:",
      "--hq-steel:", "--hq-crimson:", "--hq-forest:", "--hq-orange:",
      "--hq-lime:", "--hq-teal:",
    ]) {
      expect(rootBlock, `${token} missing from :root`).toContain(token);
    }
    expect(css).not.toContain(".hq {");
  });

  it("defines the cast's colours exactly once", () => {
    // hq.css must not re-declare a figure rule or a palette token. Two
    // declarations is two sources, and the later one wins silently.
    const hq = stripComments(read("styles/hq.css"));
    for (const forbidden of [
      ".hq-skin {", ".hq-hair {", ".hq-garment {", ".hq-portrait {",
      "--hq-skin-s", "--hq-hair-h",
      "--hq-indigo:", "--hq-cyan:", "--hq-violet:", "--hq-amber:",
      "--hq-crimson:", "--hq-teal:", "--hq-plum:", "--hq-khaki:",
    ]) {
      expect(hq, `hq.css re-declares ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("covers all ten palettes with a real token", () => {
    const css = stripComments(read("styles/characters.css"));
    const palettes = new Set(EMPLOYEES.map((e) => CHARACTERS[e.id].palette));
    for (const palette of palettes) {
      expect(css, `palette "${palette}" has no token`).toContain(`--hq-${palette}:`);
    }
  });
});

describe("the crew frames the person, not an icon", () => {
  it("renders the bust crop at readable size", () => {
    const crew = read("components/alpha/crew.tsx");
    expect(crew).toContain('frame="bust"');
    const sizes = [...crew.matchAll(/size=\{lead \? (\d+) : (\d+)\}/g)][0];
    expect(sizes, "crew portraits have no explicit sizes").toBeDefined();
    // Faces must be readable: nothing icon-sized.
    expect(Number(sizes![1])).toBeGreaterThanOrEqual(112);
    expect(Number(sizes![2])).toBeGreaterThanOrEqual(80);
  });
});
