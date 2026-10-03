import { cn } from "@/lib/utils";

/**
 * THE EXPLORATORY / FORWARD BOUNDARY
 *
 * Copy is fixed by docs/MEME_LIFECYCLE_LAB.md ("EXPLORATORY vs AUTHORITATIVE
 * DATA") and must read identically on every surface — API `data_label`, meme
 * detail, quality page. Do not reword per page; change the doc and both
 * constants together.
 */
export const EXPLORATORY_HEADLINE = "EXPLORATORY DATA";
export const EXPLORATORY_BODY =
  "Historical data may contain survivorship or look-ahead limitations. Not used for the authoritative strategy verdict.";
export const FORWARD_HEADLINE = "FORWARD DATA";
export const FORWARD_BODY =
  "Collected prospectively by MEMESCOPE. Eligible for the authoritative research dataset.";

export type DataBoundaryKind = "exploratory" | "forward";

/** Backfill anywhere on the page makes the page exploratory; label wins either way. */
export function boundaryKinds(
  dataLabel: "authoritative" | "exploratory" | null | undefined,
  containsBackfill: boolean,
): DataBoundaryKind[] {
  const exploratory = dataLabel === "exploratory" || containsBackfill;
  if (exploratory && dataLabel === "authoritative") return ["exploratory", "forward"];
  return [exploratory ? "exploratory" : "forward"];
}

export function DataBoundaryBanner({
  kind,
  className,
}: {
  kind: DataBoundaryKind;
  className?: string;
}) {
  const exploratory = kind === "exploratory";
  return (
    <div
      role="note"
      data-testid={`data-boundary-${kind}`}
      className={cn(
        "rounded-md border px-3 py-2 text-xs",
        exploratory
          ? "border-warn/30 bg-warn/10 text-ink-2"
          : "border-accent/30 bg-accent/10 text-ink-2",
        className,
      )}
    >
      <strong className={cn("font-semibold", exploratory ? "text-warn" : "text-accent")}>
        {exploratory ? EXPLORATORY_HEADLINE : FORWARD_HEADLINE}
      </strong>
      {" — "}
      {exploratory ? EXPLORATORY_BODY : FORWARD_BODY}
    </div>
  );
}
