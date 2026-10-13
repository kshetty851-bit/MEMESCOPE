import { describe, expect, it } from "vitest";
import demo from "./demo-scores.json";
import { parseScores } from "./data";
describe("advisory score imports", () => {
  it("reads the offline lab's output", () => {
    expect(parseScores(demo.map((row) => JSON.stringify(row)).join("\n"))).toHaveLength(23);
  });
  it("refuses execution permissions", () => {
    expect(() =>
      parseScores(JSON.stringify({ ...demo[0], execution_authorized: true })),
    ).toThrow("advisory");
  });
  it("rejects duplicates, invalid data and empty files", () => {
    const row = JSON.stringify(demo[0]);
    expect(() => parseScores(`${row}\n${row}`)).toThrow("repeats");
    expect(() => parseScores("{}")).toThrow("advisory");
    expect(() => parseScores("broken")).toThrow("valid JSON");
    expect(() => parseScores(" ")).toThrow("no score");
  });
});
