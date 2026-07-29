import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `BUILD` is resolved once at module load from inlined `NEXT_PUBLIC_*` values,
 * so each case has to re-import behind a fresh module registry.
 */
async function load(env: Record<string, string>) {
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }
  vi.resetModules();
  return import("@/components/alpha/alpha-bar");
}

const ALPHA_ON = {
  NEXT_PUBLIC_ALPHA: "true",
  NEXT_PUBLIC_BUILD_SHA: "a1b2c3d",
  NEXT_PUBLIC_VERSION: "0.1.0",
};

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  window.localStorage.clear();
});

describe("AlphaBar", () => {
  it("renders nothing when the alpha flag is off", async () => {
    // The default posture. Production after the alpha ends should need a flag
    // change, not a code change.
    const { AlphaBar } = await load({ NEXT_PUBLIC_ALPHA: "false" });

    const { container } = render(<AlphaBar />);

    expect(container).toBeEmptyDOMElement();
  });

  it("announces the alpha and the build when the flag is on", async () => {
    const { AlphaBar } = await load(ALPHA_ON);

    render(<AlphaBar />);

    expect(screen.getByRole("region", { name: /alpha/i })).toBeInTheDocument();
    // The SHA is the whole point: alpha reports arrive hours later and are
    // useless without knowing which build produced them.
    expect(screen.getByText(/a1b2c3d/)).toBeInTheDocument();
  });

  it("hides the feedback control when no destination is configured", async () => {
    // A button that goes nowhere collects nothing and spends the tester's
    // goodwill the first time they press it.
    const { AlphaBar } = await load({ ...ALPHA_ON, NEXT_PUBLIC_FEEDBACK_URL: "" });

    render(<AlphaBar />);

    expect(screen.queryByRole("link", { name: /feedback/i })).toBeNull();
  });

  it("shows the feedback control when a destination is configured", async () => {
    const { AlphaBar } = await load({
      ...ALPHA_ON,
      NEXT_PUBLIC_FEEDBACK_URL: "https://forms.example.com/alpha",
    });

    render(<AlphaBar />);

    const link = screen.getByRole("link", { name: /feedback/i });
    expect(link).toHaveAttribute("href", "https://forms.example.com/alpha");
    // Opening a third-party form must not hand it a window reference.
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("stays dismissed for the same build but returns on a new one", async () => {
    window.localStorage.setItem("memescope:alpha-dismissed:a1b2c3d", "1");

    const dismissed = await load(ALPHA_ON);
    const first = render(<dismissed.AlphaBar />);
    expect(first.container).toBeEmptyDOMElement();
    cleanup();

    // A new deployment is worth re-announcing: the thing being tested changed.
    const fresh = await load({ ...ALPHA_ON, NEXT_PUBLIC_BUILD_SHA: "9f8e7d6" });
    render(<fresh.AlphaBar />);

    expect(screen.getByRole("region", { name: /alpha/i })).toBeInTheDocument();
  });
});

describe("VersionBadge", () => {
  it("carries version, build and environment for a bug report", async () => {
    const { VersionBadge } = await load({
      ...ALPHA_ON,
      NEXT_PUBLIC_ENVIRONMENT: "production",
    });

    render(<VersionBadge />);

    expect(screen.getByTitle(/0\.1\.0.*a1b2c3d.*production/)).toBeInTheDocument();
  });
});
