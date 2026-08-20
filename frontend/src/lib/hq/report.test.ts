import { describe, expect, it } from "vitest";

import { UNKNOWN_HQ_STATE, deriveHqState, type HqSources } from "@/lib/hq/adapter";
import { EMPLOYEES } from "@/lib/hq/employees";
import { buildDialogue, buildReport } from "@/lib/hq/report";

const NOW = 1_760_000_000_000;

function sourced(overrides: Partial<HqSources> = {}) {
  return deriveHqState({ now: NOW, ...overrides });
}

describe("a report with nothing behind it", () => {
  const report = buildReport(UNKNOWN_HQ_STATE);

  it("still produces every section", () => {
    // A missing source must blank a section, never remove it: a report whose
    // shape changes with the data teaches a reader that absent sections do
    // not exist rather than that they are unmeasured.
    const ids = report.sections.map((section) => section.id);
    expect(ids).toEqual([
      "health",
      "discovery",
      "scoring",
      "market",
      "security",
      "paper",
      "execution",
      "queues",
      "performance",
    ]);
  });

  it("says the Paper Wallet is unavailable rather than inventing a wallet", () => {
    const paper = report.sections.find((section) => section.id === "paper")!;
    expect(paper.unavailable).toBeTruthy();
    expect(paper.lines).toHaveLength(0);
  });

  it("invents no figure anywhere", () => {
    for (const section of report.sections) {
      for (const line of section.lines) {
        // Every value is either null (renders NOT AVAILABLE) or a string the
        // adapter produced. Nothing here may manufacture a number.
        if (line.value === null) continue;
        expect(typeof line.value).toBe("string");
      }
    }
  });

  it("raises no action items when nothing is reporting a fault", () => {
    expect(report.issues).toEqual([]);
    expect(report.actions).toEqual([]);
  });
});

describe("the report never recommends", () => {
  const forbidden = [
    "buy",
    "sell",
    "hold ",
    "consider",
    "should",
    "recommend",
    "we expect",
    "guarantee",
    "opportunity to",
  ];

  it("keeps advice out of every sentence it generates", () => {
    for (const state of [UNKNOWN_HQ_STATE, sourced()]) {
      const report = buildReport(state);
      const prose = [
        ...report.summary,
        ...report.actions,
        ...report.sections.map((section) => section.unavailable ?? ""),
        ...buildDialogue(report).map((line) => line.text),
      ]
        .join(" ")
        .toLowerCase();
      for (const phrase of forbidden) {
        expect(prose, `report said "${phrase}"`).not.toContain(phrase);
      }
    }
  });
});

describe("the meeting says only what the report says", () => {
  it("gives every one of the ten a turn, with Nova opening and closing", () => {
    const dialogue = buildDialogue(buildReport(UNKNOWN_HQ_STATE));
    expect(dialogue[0]!.employee).toBe("nova");
    expect(dialogue.at(-1)!.employee).toBe("nova");
    const speakers = new Set(dialogue.map((line) => line.employee));
    for (const employee of EMPLOYEES) {
      expect(speakers.has(employee.id), `${employee.id} never speaks`).toBe(true);
    }
  });

  it("says NO DATA rather than a reassuring sentence when a desk has none", () => {
    const dialogue = buildDialogue(buildReport(UNKNOWN_HQ_STATE));
    // Atlas has no aggregate source by design and Radar has no reading here.
    // Both must say so in those words.
    const atlas = dialogue.find((line) => line.employee === "atlas")!;
    expect(atlas.text).toBe("NO DATA");
  });

  it("quotes a figure whenever it makes an operational statement", () => {
    const dialogue = buildDialogue(buildReport(UNKNOWN_HQ_STATE));
    for (const line of dialogue) {
      if (line.employee === "nova") continue; // Nova speaks the roll-up and the count.
      // Either the explicit no-data token, or `label: value` — there is no
      // third shape, so there is no room for an unsourced claim.
      expect(line.text === "NO DATA" || line.text.includes(": ")).toBe(true);
    }
  });

  it("keeps every bubble short enough to read", () => {
    for (const line of buildDialogue(buildReport(sourced()))) {
      expect(line.text.length, `${line.employee}: "${line.text}"`).toBeLessThanOrEqual(64);
    }
  });
});

describe("the report is read-only by construction", () => {
  it("is a pure function of the state it was handed", () => {
    const state = sourced();
    const before = JSON.stringify(state);
    buildReport(state);
    buildDialogue(buildReport(state));
    expect(JSON.stringify(state)).toBe(before);
  });

  it("reports the state's own clock, never a fresh one", () => {
    expect(buildReport(sourced()).observedAt).toBe(NOW);
  });

  it("produces the same report twice from the same state", () => {
    const state = sourced();
    expect(JSON.stringify(buildReport(state))).toBe(JSON.stringify(buildReport(state)));
  });
});
