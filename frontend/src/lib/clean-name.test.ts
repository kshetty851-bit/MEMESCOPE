import { describe, expect, it } from "vitest";

import { cleanName } from "./clean-name";

describe("cleanName", () => {
  it("hides obscene names, spaced or not, and keeps ordinary ones", () => {
    expect(cleanName("VAGINA")).toBe("(name hidden)");
    expect(cleanName("f.u.c.k this")).toBe("(name hidden)");
    expect(cleanName("SEX")).toBe("(name hidden)");
    for (const ok of ["ASSET", "CUMULUS", "SpiderMan", "Mii", "Sussex", "Dickens Coin", null])
      expect(cleanName(ok)).toBe(ok);
  });
});
