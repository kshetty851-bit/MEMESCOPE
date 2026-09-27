"use client";

import { useEffect, useRef } from "react";

/**
 * A METEOR HITS A PLANET, AND IT BLOWS (Karthik, 2026-09-27). Every 9-16 s a
 * glowing rock flies in from above the screen at one of the wandering planets,
 * strikes it, and bursts: a flash, a shock ring, flying debris, and the planet
 * shudders. Web Animations only (compositor work, no per-frame JavaScript);
 * nothing at all for a reader who asked for less motion.
 */
export function MeteorStrikes() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const layer = ref.current;
    if (!layer || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let timer = 0;
    let alive = true;

    const make = (className: string, x: number, y: number) => {
      const el = document.createElement("div");
      el.className = className;
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      layer.appendChild(el);
      return el;
    };

    const blast = (x: number, y: number, planetSize: number) => {
      const scale = Math.max(0.8, planetSize / 90);
      const flash = make("meteor-strike__flash", x, y);
      flash.animate(
        [{ transform: "translate(-50%, -50%) scale(0.3)", opacity: 1 },
         { transform: `translate(-50%, -50%) scale(${1.6 * scale})`, opacity: 1, offset: 0.25 },
         { transform: `translate(-50%, -50%) scale(${2.8 * scale})`, opacity: 0 }],
        { duration: 1000, easing: "cubic-bezier(.2,.8,.3,1)" },
      ).onfinish = () => flash.remove();
      const fire = make("meteor-strike__fire", x, y);
      fire.animate(
        [{ transform: "translate(-50%, -50%) scale(0.5)", opacity: 1 },
         { transform: `translate(-50%, -50%) scale(${2.4 * scale})`, opacity: 0.7, offset: 0.4 },
         { transform: `translate(-50%, -50%) scale(${3 * scale})`, opacity: 0 }],
        { duration: 1800, easing: "ease-out" },
      ).onfinish = () => fire.remove();
      const ring = make("meteor-strike__ring", x, y);
      ring.animate(
        [{ transform: "translate(-50%, -50%) scale(0.3)", opacity: 1 },
         { transform: `translate(-50%, -50%) scale(${4 * scale})`, opacity: 0 }],
        { duration: 1000, easing: "ease-out" },
      ).onfinish = () => ring.remove();
      for (let i = 0; i < 26; i++) {
        const spark = i % 3 === 0;
        const bit = make(spark ? "meteor-strike__spark" : "meteor-strike__debris", x, y);
        const angle = Math.random() * Math.PI * 2;
        const far = (spark ? 90 + Math.random() * 120 : 50 + Math.random() * 110) * scale;
        bit.animate(
          [{ transform: "translate(-50%, -50%) scale(1)", opacity: 1 },
           { opacity: 1, offset: 0.5 },
           { transform: `translate(calc(-50% + ${Math.cos(angle) * far}px), calc(-50% + ${Math.sin(angle) * far}px)) scale(0.3)`, opacity: 0 }],
          { duration: 900 + Math.random() * 700, easing: "cubic-bezier(.1,.7,.3,1)" },
        ).onfinish = () => bit.remove();
      }
    };

    const strike = () => {
      if (!alive) return;
      // Planets well inside the screen, so the whole flight can be watched.
      const bodies = Array.from(document.querySelectorAll<HTMLElement>(".planets__body")).filter((b) => {
        const r = b.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        return r.width > 0 && cx > 80 && cx < window.innerWidth - 80
          && cy > 200 && cy < window.innerHeight - 80;
      });
      const body = bodies[Math.floor(Math.random() * bodies.length)];
      if (!body || document.hidden) {
        timer = window.setTimeout(strike, 4000);
        return;
      }
      const r = body.getBoundingClientRect();
      const tx = r.left + r.width / 2;
      const ty = r.top + r.height / 2;
      const fromLeft = tx > window.innerWidth / 2;
      const sx = tx + (fromLeft ? -1 : 1) * (240 + Math.random() * 160);
      const sy = Math.max(-20, ty - (200 + Math.random() * 120));
      const angle = (Math.atan2(ty - sy, tx - sx) * 180) / Math.PI;
      const rock = make("meteor-strike__rock", 0, 0);
      rock.animate(
        [{ transform: `translate(${sx}px, ${sy}px) rotate(${angle}deg)`, opacity: 0 },
         { opacity: 1, offset: 0.15 },
         { transform: `translate(${tx}px, ${ty}px) rotate(${angle}deg)`, opacity: 1 }],
        { duration: 1300, easing: "cubic-bezier(.55,0,1,.45)" },
      ).onfinish = () => {
        rock.remove();
        blast(tx, ty, r.width);
        // `translate` is its own property, so the shudder does not fight the
        // planet's wandering `transform`.
        body.animate(
          [{ translate: "0 0", filter: "brightness(2.4) saturate(1.4)" },
           { translate: "-6px 4px", offset: 0.2 }, { translate: "5px -4px", offset: 0.4 },
           { translate: "-3px 2px", offset: 0.6 }, { translate: "0 0", filter: "none" }],
          { duration: 700, easing: "ease-out" },
        );
        timer = window.setTimeout(strike, 9000 + Math.random() * 7000);
      };
    };

    timer = window.setTimeout(strike, 3500);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      layer.replaceChildren();
    };
  }, []);

  return <div ref={ref} className="meteor-strikes" aria-hidden />;
}
