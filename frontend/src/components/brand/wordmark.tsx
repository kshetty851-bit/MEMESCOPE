import { cn } from "@/lib/utils";

/**
 * THE MEMESCOPE WORDMARK.
 *
 * Type, not paths. The first attempt drew all nine letters as SVG strokes and
 * the result was exactly what hand-drawn letterforms usually are: thin, evenly
 * spaced, and worse than any real typeface would have given for free. The
 * brief asks for typography first, and typography means using a face somebody
 * designed.
 *
 * So the word is set in Space Grotesk, and precisely one glyph is replaced.
 *
 * ── THE IDEA ────────────────────────────────────────────────────────────
 *
 * MEME | SCOPE. The word is already two halves, and the brand is the joint
 * between them: the culture, and the instrument pointed at it. The halves are
 * set in different weights — MEME light, SCOPE bold — so the eye reads the
 * split without a separator, and the O of SCOPE is the instrument itself.
 *
 * ── WHY ONLY THE O IS DRAWN ─────────────────────────────────────────────
 *
 * It is the one place a motif can live without costing legibility. A lens is
 * already a ring; an O is already a ring. Swapping it changes nothing about
 * the word's silhouette at 22px in the header, and at hero size it is the
 * detail that makes the mark specific rather than a font choice.
 *
 * The lit point inside it is deliberately *off* centre. A centred dot is a
 * crosshair, and a crosshair is a more aggressive product than this one:
 * something found, not something aimed at.
 *
 * ── WHAT IT IS NOT ──────────────────────────────────────────────────────
 *
 * No glow, no bevel, no glitch offset, no gradient across the letters. Those
 * are what make a crypto logo look like a casino, and each also destroys
 * legibility at header size — which is where this renders most of the time.
 *
 * Everything is `currentColor` and sized in `em`, so the lens tracks the type
 * automatically and one component serves the 22px header and the hero.
 */
export function Wordmark({
  className,
  title,
}: {
  className?: string;
  /** Give it an accessible name where it stands in for the product name. */
  title?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-baseline leading-none text-ink [font-family:var(--font-brand)]",
        // Tight, because two weights already separate the halves — adding
        // wide tracking as well makes it read as a government department.
        "tracking-[0.02em]",
        className,
      )}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <span className="font-light">MEME</span>
      <span className="font-bold">SC</span>
      <ScopeLens />
      <span className="font-bold">PE</span>
    </span>
  );
}

/**
 * The O of SCOPE, as a lens.
 *
 * Sized in `em` off the parent's font-size and nudged onto the baseline with
 * a fraction of the cap height, so it stays welded to the type at every size
 * rather than needing a second set of numbers per usage.
 */
function ScopeLens() {
  return (
    <svg
      viewBox="0 0 100 100"
      className="mx-[0.02em] inline-block"
      style={{ width: "0.74em", height: "0.74em", transform: "translateY(0.015em)" }}
      fill="none"
      aria-hidden="true"
    >
      {/* The bowl, at the stroke weight of the bold glyphs beside it. */}
      <circle cx="50" cy="50" r="38" stroke="currentColor" strokeWidth="17" />
      {/* Reticle ticks, stopping well short of the middle: a lens has
          graduations, a target has a cross. */}
      <g stroke="currentColor" strokeWidth="6" opacity="0.45">
        <path d="M50 4v13M50 83v13M4 50h13M83 50h13" />
      </g>
      {/* Something found. Off-centre on purpose — see the module note. */}
      <circle cx="60" cy="40" r="9" fill="currentColor" />
    </svg>
  );
}

/**
 * The subtitle under the wordmark in the hero.
 *
 * Separate, because it is optional: at header size it would be unreadable, and
 * a lockup that is illegible half the time is two lockups.
 */
export function WordmarkSubtitle({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "block font-mono text-[0.6875rem] uppercase tracking-[0.42em] text-ink-3",
        className,
      )}
    >
      Token Intelligence Command
    </span>
  );
}
