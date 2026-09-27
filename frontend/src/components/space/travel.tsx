"use client";

import { useEffect, useRef } from "react";

/**
 * TRAVELLING THROUGH SPACE (Karthik, 2026-09-27: "we should feel that we are
 * travelling in space"). Stars stream out of the middle of the screen, slowly,
 * each with a short trail, the way a starfield passes a moving ship. One
 * canvas, one requestAnimationFrame loop (the browser pauses it in a hidden
 * tab); a reader who asked for less motion gets the same stars standing still.
 */
export function SpaceTravel() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const count = window.innerWidth < 768 ? 90 : 220;
    const stars = Array.from({ length: count }, () => ({
      x: Math.random() * 2 - 1,
      y: Math.random() * 2 - 1,
      z: Math.random(),
    }));
    let w = 0;
    let h = 0;
    const size = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    window.addEventListener("resize", size);

    const SPEED = 0.055; // depth per second: a star crosses the screen in ~18 s
    const project = (s: { x: number; y: number }, z: number) => ({
      x: w / 2 + (s.x / z) * w * 0.35,
      y: h / 2 + (s.y / z) * h * 0.35,
    });
    const draw = (dt: number) => {
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        s.z -= SPEED * dt;
        if (s.z <= 0.03) {
          s.x = Math.random() * 2 - 1;
          s.y = Math.random() * 2 - 1;
          s.z = 1;
        }
        const head = project(s, s.z);
        if (head.x < -20 || head.x > w + 20 || head.y < -20 || head.y > h + 20) {
          s.z = 0; // off screen: respawn next frame
          continue;
        }
        // A short, soft trail and a bright head: a star passing, not a scratch.
        const tail = project(s, s.z + 0.012);
        const near = 1 - s.z;
        ctx.strokeStyle = `rgba(214, 228, 255, ${0.08 + near * 0.35})`;
        ctx.lineWidth = 0.3 + near * 0.9;
        ctx.beginPath();
        ctx.moveTo(tail.x, tail.y);
        ctx.lineTo(head.x, head.y);
        ctx.stroke();
        ctx.fillStyle = `rgba(240, 246, 255, ${0.25 + near * 0.7})`;
        ctx.beginPath();
        ctx.arc(head.x, head.y, 0.4 + near * 1.3, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    if (still) {
      draw(0);
      return () => window.removeEventListener("resize", size);
    }
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      draw(Math.min(0.05, (now - last) / 1000));
      last = now;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", size);
    };
  }, []);

  return <canvas ref={ref} className="home-universe__travel" aria-hidden />;
}
