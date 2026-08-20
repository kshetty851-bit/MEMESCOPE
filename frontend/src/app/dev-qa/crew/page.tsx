import { notFound } from "next/navigation";

import { Crew } from "@/components/alpha/crew";

/**
 * DEV-ONLY: the crew section alone, at the top of a page.
 *
 * Exists for one reason: the homepage hero is `min-h-dvh`, so the crew always
 * begins exactly one viewport down — and a headless browser screenshots the
 * first viewport. Every attempt to pixel-verify the section on the real
 * homepage therefore captured the hero, however tall the window. This route
 * removes the hero, so `--screenshot` lands on the thing being verified.
 *
 * It renders the identical component over the identical data and stylesheets;
 * nothing is re-declared here, so what this page proves holds on the homepage.
 *
 * Not part of the product: production builds 404 it.
 */
export default function CrewQaPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main style={{ padding: "2rem 0", background: "var(--color-bg)" }}>
      <Crew />
    </main>
  );
}
