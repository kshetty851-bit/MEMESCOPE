"use client";

import Image from "next/image";
import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export function HeroMascot({
  active = false,
  compact = false,
}: {
  active?: boolean;
  compact?: boolean;
}) {
  const [gaze, setGaze] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (compact || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const x = (event.clientX / window.innerWidth - 0.5) * 10;
        const y = (event.clientY / window.innerHeight - 0.5) * 8;
        setGaze({ x, y });
      });
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
    };
  }, [compact]);

  return (
    <div
      className={cn(
        "alpha-mascot lm-mascot",
        compact ? "alpha-mascot--compact" : "alpha-mascot--hero",
        active && "alpha-mascot--unlock",
      )}
      style={
        {
          "--gaze-x": `${gaze.x}px`,
          "--gaze-y": `${gaze.y}px`,
        } as CSSProperties
      }
      aria-hidden
    >
      <div className="lm-mascot__drift">
        <div className="lm-mascot__breathe alpha-mascot__frame">
          <span className="alpha-mascot__shadow" />
          <span className="alpha-mascot__backlight" />
          <Image
            src="/mascot/frog-astronaut-cutout.png"
            alt=""
            width={1024}
            height={1536}
            priority={!compact}
            sizes={compact ? "120px" : "(max-width: 900px) 68vw, 42vw"}
            className="alpha-mascot__image"
          />
          <span className="alpha-mascot__atmosphere" />
          <span className="alpha-mascot__reflection lm-mascot__shimmer" />
          <span className="alpha-mascot__blink alpha-mascot__blink--left" />
          <span className="alpha-mascot__blink alpha-mascot__blink--right" />
          <span className="alpha-mascot__hand" />
          <span className="alpha-mascot__helmet-light" />
        </div>
      </div>
    </div>
  );
}
