"use client";

import { useEffect, useState } from "react";

/**
 * SPACE KNOWLEDGE, TOP LEFT (Karthik, 2026-09-27: "keep providing space
 * knowledge"). One short fact at a time, changing every eight seconds, in a
 * random order each visit. Every line is a well-established figure; where a
 * number is an estimate it says so.
 */
export const FACTS: readonly string[] = [
  "Sunlight takes about 8 minutes 20 seconds to reach Earth.",
  "A day on Venus (243 Earth days) is longer than its year (225 days).",
  "Saturn is less dense than water — in a big enough bath, it would float.",
  "About 1.3 million Earths would fit inside the Sun.",
  "The Sun holds about 99.8% of all the mass in the Solar System.",
  "Olympus Mons on Mars is about 2.5 times the height of Mount Everest.",
  "Light from Proxima Centauri, the nearest star after the Sun, takes 4.2 years to reach us.",
  "The Milky Way holds an estimated 100 to 400 billion stars.",
  "Jupiter's Great Red Spot is a storm wider than the whole Earth.",
  "The International Space Station circles Earth about every 90 minutes.",
  "A year on Mercury lasts just 88 Earth days.",
  "Space is silent: sound needs air, or something else, to travel through.",
  "Mars is red because its dust is full of iron oxide — rust.",
  "Neptune's winds reach over 2,000 km/h, the fastest in the Solar System.",
  "The observable universe is about 93 billion light-years across.",
  "Voyager 1, launched in 1977, is more than 24 billion km away — the farthest spacecraft.",
  "A teaspoon of neutron star would weigh billions of tonnes.",
  "The Moon drifts about 3.8 cm further from Earth every year.",
  "Uranus spins on its side, tilted about 98 degrees.",
  "Yuri Gagarin became the first human in space on 12 April 1961.",
  "Apollo 11 landed on the Moon on 20 July 1969.",
  "The Sun is about 4.6 billion years old.",
  "Astronauts can grow up to about 5 cm taller in space as their spines stretch.",
  "The Andromeda galaxy, 2.5 million light-years away, can be seen without a telescope.",
  "Some neutron stars spin more than 700 times a second.",
  "Footprints on the Moon can last for millions of years — there is no wind to erase them.",
];

const EVERY_MS = 8000;

/**
 * A holographic transmission card. `toFrog` adds the pointer on its right,
 * for the desktop spot beside the frog (Karthik, 2026-09-27: "near frog,
 * very stylish and attractive").
 */
export function SpaceFacts({ className = "", toFrog = false }: { className?: string; toFrog?: boolean }) {
  const [order, setOrder] = useState<number[] | null>(null);
  const [at, setAt] = useState(0);

  // Shuffled on the client only, so the server and first client render agree.
  useEffect(() => {
    setOrder(FACTS.map((_, i) => i).sort(() => Math.random() - 0.5));
    const timer = window.setInterval(() => setAt((n) => n + 1), EVERY_MS);
    return () => window.clearInterval(timer);
  }, []);

  if (!order) return null;
  const index = order[at % order.length]!;
  return (
    <div
      className={`space-facts ${toFrog ? "space-facts--to-frog" : ""} ${className}`}
      role="status"
      aria-live="polite"
    >
      <div className="space-facts__head">
        <span className="space-facts__orbit" aria-hidden>
          <span />
        </span>
        <span className="space-facts__label">Space fact</span>
        <span className="space-facts__count">
          {String((at % order.length) + 1).padStart(2, "0")} / {FACTS.length}
        </span>
      </div>
      <p key={at} className="space-facts__text">
        {FACTS[index]}
      </p>
      <span key={`bar-${at}`} className="space-facts__bar" aria-hidden />
    </div>
  );
}
