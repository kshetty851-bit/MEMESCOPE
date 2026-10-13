import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PretradeAIPage } from "./page";
vi.mock("./live", () => ({ LivePaperLab: () => <div>Paper lab</div> }));
afterEach(cleanup);
describe("Pre-trade AI lab", () => {
  it("keeps imported synthetic results separate from the paper book", () => {
    render(<PretradeAIPage />);
    expect(screen.getByText("Offline file viewer")).toBeInTheDocument();
    expect(screen.getByText("Your research starts with evidence")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explore sample" }));
    expect(screen.getByRole("status")).toHaveTextContent("SYNTHETIC SAMPLE");
    fireEvent.change(screen.getByRole("textbox", { name: "Search candidates" }), {
      target: { value: "does-not-exist" },
    });
    expect(screen.getByText("No candidates match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear results" }));
    expect(screen.getByText("Your research starts with evidence")).toBeInTheDocument();
  });
  it("shows an explanation without an execution action", () => {
    render(<PretradeAIPage />);
    fireEvent.click(screen.getByRole("button", { name: "Explore sample" }));
    fireEvent.click(screen.getAllByRole("button", { name: /^Review demo-/ })[0]!);
    expect(screen.getByRole("region", { name: "Candidate details" })).toHaveTextContent(
      "Decision explanation",
    );
    expect(
      screen.queryByRole("button", { name: /execute|buy|trade now/i }),
    ).not.toBeInTheDocument();
  });
});
