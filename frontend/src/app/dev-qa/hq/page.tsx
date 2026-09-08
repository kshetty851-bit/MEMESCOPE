"use client";

import { notFound } from "next/navigation";

import { HqStage } from "@/components/hq/hq-stage";
import { useAmbient } from "@/components/hq/use-ambient";
import { useDayPhase } from "@/components/hq/use-hq-env";
import { UNKNOWN_HQ_STATE } from "@/lib/hq/adapter";
import { EMPLOYEES } from "@/lib/hq/employees";

/**
 * DEV-ONLY: the isometric office alone, outside the alpha gate.
 *
 * The dashboard shell holds rendering until the API confirms an alpha session,
 * so with no local backend `/hq` never draws — it redirects. This route mounts
 * the identical `HqStage` over the identical stylesheets with the all-UNKNOWN
 * state the stage already defaults to, and runs the real ambient scheduler so
 * the cast is posed rather than parked. Same pattern as `dev-qa/crew`, same
 * reason: a headless browser needs the thing being verified in the first
 * viewport.
 *
 * Nothing is re-declared here, so what this page shows is what `/hq` shows.
 * Not part of the product: production builds 404 it.
 */
export default function HqQaPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Preview />;
}

const noop = () => {};

function Preview() {
  const phase = useDayPhase();
  const ambient = useAmbient(
    true,
    EMPLOYEES.map((employee) => employee.id),
    "NORMAL",
    phase,
  );
  return (
    <main style={{ padding: "1rem", background: "var(--color-bg)" }}>
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={UNKNOWN_HQ_STATE}
        frames={ambient.frames}
        visibleCases={[]}
        caseOverflow={0}
        onSelectCase={noop}
      />
    </main>
  );
}
