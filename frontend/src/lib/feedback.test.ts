import { afterEach, describe, expect, it, vi } from "vitest";

async function load(env: Record<string, string> = {}) {
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
  vi.resetModules();
  return import("@/lib/feedback");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("buildReport", () => {
  it("attaches the page and build so a report can be traced", async () => {
    // Alpha reports arrive hours later as "the scores looked wrong". Without
    // these two fields there is no way to reconstruct what was on screen.
    const { buildReport } = await load({ NEXT_PUBLIC_BUILD_SHA: "a1b2c3d" });

    const report = buildReport("bug", "  something broke  ");

    expect(report.build).toBe("a1b2c3d");
    expect(report.path).toBe(window.location.pathname);
    expect(report.message).toBe("something broke");
    expect(report.submittedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

describe("submitFeedback", () => {
  it("posts to the endpoint when one is configured", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    const { buildReport, submitFeedback } = await load({
      NEXT_PUBLIC_FEEDBACK_ENDPOINT: "https://api.example.com/feedback",
    });

    const outcome = await submitFeedback(buildReport("bug", "broken"));

    expect(outcome.status).toBe("sent");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example.com/feedback");
  });

  it("hands the report back rather than losing it when the network fails", async () => {
    // A tester who has written three paragraphs about a bug must never lose
    // them to a fetch error.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    const { buildReport, submitFeedback } = await load({
      NEXT_PUBLIC_FEEDBACK_ENDPOINT: "https://api.example.com/feedback",
    });

    const outcome = await submitFeedback(buildReport("bug", "important detail"));

    expect(outcome.status).toBe("failed");
    if (outcome.status === "failed") {
      expect(outcome.report.message).toBe("important detail");
    }
  });

  it("treats a non-ok response as a failure, not a success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));

    const { buildReport, submitFeedback } = await load({
      NEXT_PUBLIC_FEEDBACK_ENDPOINT: "https://api.example.com/feedback",
    });

    const outcome = await submitFeedback(buildReport("bug", "x"));

    expect(outcome.status).toBe("failed");
    if (outcome.status === "failed") expect(outcome.error).toContain("502");
  });

  it("falls back to an external form when only a URL is configured", async () => {
    const { buildReport, submitFeedback } = await load({
      NEXT_PUBLIC_FEEDBACK_URL: "https://forms.example.com/alpha",
    });

    const outcome = await submitFeedback(buildReport("suggestion", "x"));

    expect(outcome).toEqual({
      status: "redirected",
      url: "https://forms.example.com/alpha",
    });
  });

  it("prefers the endpoint over the external form", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    const { buildReport, submitFeedback } = await load({
      NEXT_PUBLIC_FEEDBACK_ENDPOINT: "https://api.example.com/feedback",
      NEXT_PUBLIC_FEEDBACK_URL: "https://forms.example.com/alpha",
    });

    expect((await submitFeedback(buildReport("bug", "x"))).status).toBe("sent");
  });

  it("returns the report for copying when nothing is configured", async () => {
    // The default state during this alpha. Silently discarding the text would
    // be the one unacceptable outcome.
    const { buildReport, submitFeedback } = await load();

    const outcome = await submitFeedback(buildReport("general", "hello"));

    expect(outcome.status).toBe("unconfigured");
    if (outcome.status === "unconfigured") {
      expect(outcome.report.message).toBe("hello");
    }
  });
});

describe("formatReport", () => {
  it("renders a copyable report carrying page and build", async () => {
    const { buildReport, formatReport } = await load({
      NEXT_PUBLIC_BUILD_SHA: "a1b2c3d",
    });

    const text = formatReport(buildReport("feature", "add a watchlist"));

    expect(text).toContain("[Feature request]");
    expect(text).toContain("add a watchlist");
    expect(text).toContain("a1b2c3d");
  });
});
