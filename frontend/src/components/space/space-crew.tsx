"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * THE SPACE CREW — the animal astronauts, added 2026-09-24 at the owner's
 * request: some sitting on the wordmark, the rest floating in the scene.
 *
 * Three places, each a separate component because each lives in a different
 * layer of the page:
 *
 *  - PerchedCrew sits ON the wordmark, inside the hero copy. Its sizes and
 *    offsets are in `em` of the wordmark's own font size, so on a phone and on
 *    a 1920 monitor the same animals sit on the same letters. The letters' top
 *    edge is 0.37em below the wordmark box (measured: the lens glyph, which is
 *    exactly cap height, starts there).
 *
 *  - FloatingCrew is two fixed layers. The FRONT one sits above the page copy
 *    so the animals can be hovered, and holds only figures parked in the free
 *    corners measured at 1024x768 through 1920x1080 (see space-crew.css): it
 *    must never cover the copy or the access form. The BACK one sits between
 *    the scene and the copy and carries the fly-bys, which cross the whole
 *    frame and so must pass BEHIND the copy.
 *
 *  - CardPeeker is an animal behind a card, showing over its top edge.
 *
 * Everything moves in CSS on transform and opacity only. The crew leaves when
 * the hero scrolls away and comes back with it. With reduced motion the
 * parked figures stand still and the fly-bys and peekaboos do not happen.
 */

type Sprite = { src: string; alt?: string };

function Img({ src, className }: Sprite & { className?: string }) {
  // Decorative: named in the page's own copy, not by these pictures.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" aria-hidden draggable={false} decoding="async" className={className} />
  );
}

/** Hippo, panda and penguin, sitting on MEMESCOPE. */
export function PerchedCrew() {
  return (
    <span className="crew-perch" aria-hidden>
      <span className="crew-perch__seat crew-perch__seat--hippo">
        <Img src="/crew/hippo.webp" className="crew-perch__img" />
      </span>
      <span className="crew-perch__seat crew-perch__seat--panda">
        <Img src="/crew/panda.webp" className="crew-perch__img" />
      </span>
      <span className="crew-perch__seat crew-perch__seat--penguin">
        <Img src="/crew/penguin.webp" className="crew-perch__img" />
      </span>
    </span>
  );
}

/** Away once the hero is mostly scrolled past; back when it returns. */
function useHeroAway(): boolean {
  const [away, setAway] = useState(false);
  useEffect(() => {
    let frame = 0;
    const read = () => {
      frame = 0;
      setAway(window.scrollY > window.innerHeight * 0.45);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    read();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return away;
}

export function FloatingCrew() {
  const away = useHeroAway();
  const state = { "data-away": away ? "" : undefined };
  return (
    <>
      <div className="crew-sky crew-sky--back" aria-hidden {...state}>
        <div className="crew-flyby crew-flyby--hamster">
          <Img src="/crew/hamster.webp" className="crew-flyby__img" />
        </div>
        <div className="crew-flyby crew-flyby--toucan">
          <Img src="/crew/toucan.webp" className="crew-flyby__img" />
        </div>
      </div>

      <div className="crew-sky crew-sky--front" aria-hidden {...state}>
        <div className="crew-float crew-float--fox">
          <Img src="/crew/fox.webp" className="crew-float__img" />
        </div>
        <div className="crew-float crew-float--toucan-bubble">
          <Img src="/crew/toucan-bubble.webp" className="crew-float__img" />
        </div>
        <div className="crew-float crew-float--monkey">
          <Img src="/crew/monkey.webp" className="crew-float__img" />
        </div>
        <div className="crew-float crew-float--giraffe">
          <Img src="/crew/giraffe.webp" className="crew-float__img" />
        </div>
      </div>
    </>
  );
}

/** An animal behind a card, showing over its top edge; it rises when the card
 *  is hovered (the card's `group` class drives it). */
export function CardPeeker({ src, side = "right" }: { src: string; side?: "left" | "right" }) {
  return (
    <span className={cn("crew-peek", side === "left" ? "crew-peek--left" : "crew-peek--right")} aria-hidden>
      <Img src={src} className="crew-peek__img" />
    </span>
  );
}
