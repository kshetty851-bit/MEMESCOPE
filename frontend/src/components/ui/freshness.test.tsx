import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  FreshnessLabel,
  LiveStatus,
  NoMarketData,
} from "@/components/ui/freshness";

/**
 * The freshness indicators.
 *
 * Every assertion here is about a distinction the product previously collapsed:
 * loading is not "no data", "no data" is not "stale", and a timestamp is not a
 * promise that the next one is coming.
 */

const ago = (seconds: number) =>
  new Date(Date.now() - seconds * 1000).toISOString();

afterEach(cleanup);

describe("FreshnessLabel", () => {
  it("shows the age on the face of the row", () => {
    render(<FreshnessLabel capturedAt={ago(12)} />);
    expect(screen.getByText("Updated 12 sec ago")).toBeInTheDocument();
  });

  it("never renders the word 'live' in place of an age", () => {
    // "Live" is a promise about the future; a timestamp is a fact about the
    // past, and only one of them can be checked.
    const { container } = render(<FreshnessLabel capturedAt={ago(3)} />);
    expect((container.textContent ?? "").toLowerCase()).not.toContain("live");
  });

  it("says a token was never priced rather than showing an age", () => {
    render(<FreshnessLabel capturedAt={null} />);
    expect(screen.getByText("No market data")).toBeInTheDocument();
  });

  it("carries a spelled-out description for screen readers", () => {
    render(<FreshnessLabel capturedAt={ago(120)} />);
    expect(
      screen.getByText("Market data last observed 2 min ago."),
    ).toBeInTheDocument();
  });
});

describe("LiveStatus", () => {
  it("renders nothing while the page is still loading", () => {
    // Found in live verification: the Track Record showed "No market data"
    // during its fetch, which is a false claim about the data rather than a
    // true one about the request.
    const { container } = render(<LiveStatus timestamps={[]} pending />);
    expect(container).toBeEmptyDOMElement();
  });

  it("distinguishes 'nothing observed' from 'still loading'", () => {
    render(<LiveStatus timestamps={[]} />);
    expect(screen.getByText("No market data")).toBeInTheDocument();
  });

  it("reports live beside the age, never on its own", () => {
    render(<LiveStatus timestamps={[ago(8)]} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
    // A badge saying LIVE next to a three-minute-old price is the dishonesty
    // this component exists to remove.
    expect(screen.getByText(/updated 8 sec ago/)).toBeInTheDocument();
  });

  it("stops claiming live once the newest reading has aged out", () => {
    render(<LiveStatus timestamps={[ago(3_600)]} />);
    expect(screen.getByText("Waiting for market data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("reports the freshest reading, so one stale row does not imply a dead pipeline", () => {
    render(<LiveStatus timestamps={[ago(9_000), ago(5), ago(400)]} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});

describe("NoMarketData", () => {
  it("states the token is still being polled rather than implying it was dropped", () => {
    render(<NoMarketData />);
    const node = screen.getByText("Waiting for liquidity");
    expect(node).toBeInTheDocument();
    expect(node.getAttribute("title")).toContain("still being polled");
  });
});
