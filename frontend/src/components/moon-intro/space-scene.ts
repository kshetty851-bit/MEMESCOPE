/**
 * SPACE CANVAS — the view through the canopy. Canvas 2D, all procedural.
 *
 * The controller owns the clock: it calls `update(frame)` once per rAF and
 * `resize()` on window resize. Nothing here schedules frames of its own.
 *
 * Hot-path rules: no allocation per frame (typed arrays, constant style
 * strings), no shadowBlur / filter, and every expensive picture (moon, ground,
 * rocks, retro flare) is baked ONCE to an offscreen canvas and drawImage'd.
 * All drawing is in device pixels (DPR capped at 2).
 */
import { ASTEROID_LABELS, MOMENTS, type Frame } from "./timeline";

export type Quality = "high" | "low";
export type SpaceScene = {
  update(frame: Frame): void;
  resize(): void;
  destroy(): void;
  quality(): Quality;
};

export const STAR_COUNTS = { high: 480, low: 180 } as const;
export const DUST_COUNTS = { high: 220, low: 70 } as const;
/** A frame slower than SLOW_FRAME_MS is slow; SLOW_FRAMES in a row drops to "low", for good. */
export const SLOW_FRAME_MS = 20;
export const SLOW_FRAMES = 30;

const TAU = Math.PI * 2;
const BG = "#02030a";
const GREEN = "#35e08a";
const RED = "#ff4d5e";
// Star groups, one path each: dim, white, cyan, green candle, red candle (15% candles).
const SHARE = [0.4, 0.3, 0.15, 0.075, 0.075];
const DOT = ["#6f7899", "#ffffff", "#9be8ff", "#c9d2ff", "#ffffff"];
const STREAK = ["#8fa0c8", "#ffffff", "#9be8ff", GREEN, RED];
const MOON_R = 0.42; // disc radius as a fraction of the baked texture; the rest is rim glow
const HORIZON = 0.52; // horizon line, fraction of viewport height
// Fly-by rocks: [direction (rad), delay (phase fraction), size (x min viewport), spin].
const ROCKS = [
  [-2.5, 0, 0.1, 2.2],
  [-0.35, 0.035, 0.08, -3],
  [2.3, 0.07, 0.09, 2.6],
] as const;
const ROCK_SPAN = 0.14;
const NEAR_SPAN = 0.08;

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);

/** Moon diameter as a fraction of min(viewport) through approach: a dot, easing in to 80%. */
export function moonScale(p: number): number {
  const q = clamp01(p);
  return 0.015 + 0.785 * q * q;
}

/** Stars per group for a tier, summing exactly to the tier's count. */
export function groupSizes(total: number): number[] {
  const n = SHARE.map((s) => Math.floor(total * s));
  n[0] = (n[0] ?? 0) + total - n.reduce((a, b) => a + b, 0);
  return n;
}

function mulberry32(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function bake(w: number, h: number, draw: (c: CanvasRenderingContext2D) => void) {
  const el = document.createElement("canvas");
  el.width = w;
  el.height = h;
  const c = el.getContext("2d");
  if (!c) return null;
  draw(c);
  return el;
}

/** Bowl crater lit from the upper left: dark floor, shadowed near rim, bright far rim. */
function crater(c: CanvasRenderingContext2D, x: number, y: number, rx: number, ry = rx) {
  c.fillStyle = "rgba(28,28,42,0.16)";
  c.beginPath();
  c.ellipse(x, y, rx, ry, 0, 0, TAU);
  c.fill();
  c.lineWidth = Math.max(1, rx * 0.1);
  c.strokeStyle = "rgba(0,0,12,0.3)";
  c.beginPath();
  c.ellipse(x, y, rx * 0.9, ry * 0.9, 0, Math.PI * 0.75, Math.PI * 1.75);
  c.stroke();
  c.strokeStyle = "rgba(255,255,255,0.22)";
  c.beginPath();
  c.ellipse(x, y, rx, ry, 0, -Math.PI * 0.25, Math.PI * 0.75);
  c.stroke();
}

/** A planted flag (green candle on the cloth) with a dotted trail of bootprints. */
function flag(c: CanvasRenderingContext2D, x: number, y: number, k: number) {
  c.fillStyle = "rgba(20,20,30,0.55)";
  for (let i = 0; i < 14; i++) {
    const t = i / 13;
    const side = i % 2 ? 3 : -3;
    c.fillRect(x - 10 * k - t * 70 * k + side * k, y + 5 * k + t * 48 * k + Math.sin(t * 6) * 6 * k, 3 * k, 4 * k);
  }
  c.fillStyle = "rgba(0,0,10,0.35)";
  c.fillRect(x, y, 24 * k, 2 * k); // pole shadow, falling away from the light
  c.fillStyle = "#e8e8ee";
  c.fillRect(x - k, y - 32 * k, 2 * k, 32 * k);
  c.fillStyle = "#2a8fd6";
  c.fillRect(x + k, y - 32 * k, 20 * k, 13 * k);
  c.fillStyle = GREEN;
  c.fillRect(x + 9 * k, y - 29 * k, 4 * k, 7 * k);
  c.fillRect(x + 10.5 * k, y - 31 * k, k, 11 * k);
}

function bakeMoon(size: number, glow: boolean) {
  return bake(size, size, (c) => {
    const rnd = mulberry32(42);
    const C = size / 2;
    const R = size * MOON_R;
    const k = (size / 1024) * 1.6; // detail scale: readable once the moon fills the canopy
    if (glow) {
      const g = c.createRadialGradient(C, C, R * 0.97, C, C, R * 1.18);
      g.addColorStop(0, "rgba(190,210,255,0.3)");
      g.addColorStop(1, "rgba(190,210,255,0)");
      c.fillStyle = g;
      c.fillRect(0, 0, size, size);
    }
    c.save();
    c.beginPath();
    c.arc(C, C, R, 0, TAU);
    c.clip();
    const base = c.createRadialGradient(C - R * 0.35, C - R * 0.35, R * 0.1, C, C, R * 1.05);
    base.addColorStop(0, "#e6e6ec");
    base.addColorStop(0.6, "#a9a9b3");
    base.addColorStop(1, "#6c6c78");
    c.fillStyle = base;
    c.fillRect(0, 0, size, size);
    c.fillStyle = "rgba(70,72,92,0.16)"; // maria
    for (let i = 0; i < 7; i++) {
      const x = C + (rnd() - 0.5) * R * 1.4;
      const y = C + (rnd() - 0.5) * R * 1.4;
      for (let j = 0; j < 3; j++) {
        c.beginPath();
        c.arc(x + (rnd() - 0.5) * R * 0.2, y + (rnd() - 0.5) * R * 0.2, R * (0.08 + rnd() * 0.14), 0, TAU);
        c.fill();
      }
    }
    for (let i = 0; i < 170; i++) {
      const a = rnd() * TAU;
      const d = Math.sqrt(rnd()) * R;
      const x = C + Math.cos(a) * d;
      const y = C + Math.sin(a) * d;
      // Keep the close-up detail patch in the middle clean.
      if (Math.abs(x - C) < 90 * k && Math.abs(y - C) < 70 * k) continue;
      crater(c, x, y, size * (0.004 + 0.05 * rnd() ** 4));
    }
    // The candlestick crater: a green body sunk in the regolith, with its wick.
    const bx = C - 58 * k;
    const by = C - 40 * k;
    c.fillStyle = "rgba(10,30,20,0.55)";
    c.fillRect(bx + 7 * k, by - 22 * k, 3 * k, 80 * k);
    c.fillRect(bx - 2 * k, by - 2 * k, 20 * k, 40 * k);
    c.fillStyle = GREEN;
    c.fillRect(bx, by, 17 * k, 37 * k);
    c.fillStyle = "rgba(255,255,255,0.35)";
    c.fillRect(bx, by + 35 * k, 17 * k, 2 * k);
    c.fillRect(bx + 15 * k, by, 2 * k, 37 * k);
    flag(c, C + 50 * k, C + 8 * k, k);
    const term = c.createLinearGradient(C + R * 0.05, 0, C + R, 0);
    term.addColorStop(0, "rgba(4,5,14,0)");
    term.addColorStop(0.55, "rgba(4,5,14,0.72)");
    term.addColorStop(1, "rgba(4,5,14,0.96)");
    c.fillStyle = term;
    c.fillRect(0, 0, size, size);
    c.restore();
  });
}

function bakeGround(W: number, H: number) {
  return bake(W, H, (c) => {
    const rnd = mulberry32(7);
    const g = c.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#3a3a44");
    g.addColorStop(0.18, "#5b5b66");
    g.addColorStop(1, "#a2a2aa");
    c.fillStyle = g;
    c.fillRect(0, 0, W, H);
    for (let i = 0; i < 600; i++) {
      const y = H * rnd();
      const s = 1 + (y / H) * 3 * rnd();
      c.fillStyle = i % 2 ? "rgba(0,0,0,0.14)" : "rgba(255,255,255,0.1)";
      c.fillRect(W * rnd(), y, s, s * 0.6);
    }
    for (let i = 0; i < 45; i++) {
      const y = H * (0.04 + 0.96 * rnd() ** 1.4);
      const persp = y / H;
      const rx = (6 + 110 * rnd() ** 2) * (0.2 + persp);
      crater(c, W * rnd(), y, rx, rx * (0.2 + 0.3 * persp));
    }
    flag(c, W * 0.64, H * 0.3, 0.9);
  });
}

function bakeRock(seed: number) {
  const S = 160;
  return bake(S, S, (c) => {
    const rnd = mulberry32(seed);
    c.beginPath();
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * TAU;
      const r = S * 0.42 * (0.7 + 0.3 * rnd());
      c.lineTo(S / 2 + Math.cos(a) * r, S / 2 + Math.sin(a) * r * 0.85);
    }
    c.closePath();
    const g = c.createRadialGradient(S * 0.35, S * 0.32, S * 0.05, S / 2, S / 2, S * 0.5);
    g.addColorStop(0, "#bdb4a6");
    g.addColorStop(0.6, "#5e574e");
    g.addColorStop(1, "#231f1b");
    c.fillStyle = g;
    c.fill();
    c.save();
    c.clip();
    for (let i = 0; i < 4; i++) crater(c, S * (0.3 + 0.4 * rnd()), S * (0.3 + 0.4 * rnd()), S * (0.04 + 0.06 * rnd()));
    c.restore();
  });
}

function bakeFlare() {
  const S = 256;
  return bake(S, S, (c) => {
    const g = c.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    g.addColorStop(0, "rgba(255,250,235,1)");
    g.addColorStop(0.3, "rgba(255,185,95,0.7)");
    g.addColorStop(1, "rgba(255,90,20,0)");
    c.fillStyle = g;
    c.fillRect(0, 0, S, S);
  });
}

export function createSpaceScene(canvas: HTMLCanvasElement, opts: { mobile?: boolean } = {}): SpaceScene {
  const ctx = canvas.getContext("2d");
  let tier: Quality = opts.mobile ? "low" : "high";
  let slow = 0;
  let dead = false;

  let mono = 'ui-monospace, "Geist Mono", monospace';
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue("--font-geist-mono").trim();
    if (v) mono = `${v}, ${mono}`;
  } catch {
    /* keep the fallback */
  }

  const moonTex = ctx ? bakeMoon(opts.mobile ? 768 : 1024, !opts.mobile) : null;
  const groundTex = ctx ? bakeGround(1024, 512) : null;
  const rockTex = ctx ? [bakeRock(3), bakeRock(11), bakeRock(29)] : [];
  const flareTex = ctx ? bakeFlare() : null;

  // Stars: grouped by colour, so each group is one path. A tier draws the first n of each group.
  const N = STAR_COUNTS.high;
  const X = new Float32Array(N);
  const Y = new Float32Array(N);
  const Z = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    X[i] = (Math.random() - 0.5) * 2.4;
    Y[i] = (Math.random() - 0.5) * 2.4;
    Z[i] = 0.02 + Math.random() * 0.98;
  }
  const SIZES = { high: groupSizes(STAR_COUNTS.high), low: groupSizes(STAR_COUNTS.low) };
  const START = SIZES.high.map((_, g) => SIZES.high.slice(0, g).reduce((a, b) => a + b, 0));

  const DN = DUST_COUNTS.high;
  const DX = new Float32Array(DN);
  const DY = new Float32Array(DN);
  const DVX = new Float32Array(DN);
  const DVY = new Float32Array(DN);
  const DL = new Float32Array(DN);
  const DM = new Float32Array(DN);
  let dustN = 0;
  let dustDone = false;

  let w = 1;
  let h = 1;
  let dpr = 1;
  let cx = 0;
  let cy = 0;
  let minD = 1;
  let f = 1;
  let fonts = ["", ""];
  let still = false; // reduced mode: the one static frame is on screen
  let lastT = -1;
  let phase = "";
  let phaseT0 = 0;

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round((canvas.clientWidth || window.innerWidth) * dpr));
    canvas.height = Math.max(1, Math.round((canvas.clientHeight || window.innerHeight) * dpr));
    w = canvas.width;
    h = canvas.height;
    cx = w / 2;
    cy = h / 2;
    minD = Math.min(w, h);
    f = Math.max(w, h) / 2;
    fonts = [1, 1.6].map((k) => `bold ${Math.round(12 * k * dpr)}px ${mono}`);
    still = false;
  }

  function step(dz: number) {
    if (dz <= 0) return;
    for (let i = 0; i < N; i++) {
      const z = Z[i]! - dz;
      Z[i] = z;
      if (z < 0.02) {
        Z[i] = z + 0.98;
        X[i] = (Math.random() - 0.5) * 2.4;
        Y[i] = (Math.random() - 0.5) * 2.4;
      }
    }
  }

  function sky(frac: number, alpha: number) {
    const c = ctx!;
    c.globalAlpha = alpha;
    c.fillStyle = BG;
    c.fillRect(0, 0, w, h);
    const sizes = SIZES[tier];
    for (let g = 0; g < 5; g++) {
      c.fillStyle = DOT[g]!;
      c.beginPath();
      const end = START[g]! + Math.ceil(sizes[g]! * frac);
      for (let i = START[g]!; i < end; i++) {
        const z = Z[i]!;
        const s = (1.3 - z) * 1.4 * dpr;
        c.rect(cx + (X[i]! / z) * f - s / 2, cy + (Y[i]! / z) * f - s / 2, s, s);
      }
      c.fill();
    }
    c.globalAlpha = 1;
  }

  function streaks(len: number, alpha: number) {
    const c = ctx!;
    c.fillStyle = BG;
    c.fillRect(0, 0, w, h);
    c.globalAlpha = alpha;
    const sizes = SIZES[tier];
    for (let pass = 0; pass < 7; pass++) {
      const body = pass >= 5; // passes 5,6 draw the candle bodies of groups 3,4
      const g = body ? pass - 2 : pass;
      c.strokeStyle = STREAK[g]!;
      c.lineWidth = (body ? 4 : g === 0 ? 1 : 1.5) * dpr;
      c.beginPath();
      const end = START[g]! + sizes[g]!;
      for (let i = START[g]!; i < end; i++) {
        const hz = Z[i]!;
        const sx = X[i]!;
        const sy = Y[i]!;
        const tz = hz + len;
        const hx = cx + (sx / hz) * f;
        const hy = cy + (sy / hz) * f;
        const tx = cx + (sx / tz) * f;
        const ty = cy + (sy / tz) * f;
        if (body) {
          c.moveTo(tx + (hx - tx) * 0.3, ty + (hy - ty) * 0.3);
          c.lineTo(tx + (hx - tx) * 0.75, ty + (hy - ty) * 0.75);
        } else {
          c.moveTo(tx, ty);
          c.lineTo(hx, hy);
        }
      }
      c.stroke();
    }
    c.globalAlpha = 1;
  }

  function moon(frac: number) {
    if (!moonTex) return;
    const T = (frac * minD) / (2 * MOON_R);
    ctx!.drawImage(moonTex, cx - T / 2, cy - T / 2, T, T);
  }

  function landed(zoom: number, alpha: number) {
    sky(1, alpha);
    if (!groundTex) return;
    const hy = h * HORIZON;
    const gw = w * 1.1 * zoom;
    ctx!.globalAlpha = alpha;
    ctx!.drawImage(groundTex, cx - gw / 2, hy, gw, (h - hy) * 1.05 * zoom);
    ctx!.globalAlpha = 1;
  }

  function rock(i: number, x: number, y: number, s: number, rot: number) {
    const tex = rockTex[i % rockTex.length];
    if (!tex) return;
    const c = ctx!;
    c.translate(x, y);
    c.rotate(rot);
    c.drawImage(tex, -s / 2, -s / 2, s, s);
    c.setTransform(1, 0, 0, 1, 0, 0);
  }

  function asteroids(p: number) {
    const c = ctx!;
    c.textAlign = "center";
    c.textBaseline = "top";
    ROCKS.forEach(([a, delay, size, spin], i) => {
      const q = (p - MOMENTS.approach.asteroids - delay) / ROCK_SPAN;
      if (q <= 0 || q >= 1) return;
      const e = q * q;
      const r = (0.12 + 1.5 * e) * minD * 0.5;
      const s = size * minD * (0.35 + 2.5 * e);
      const x = cx + Math.cos(a) * r;
      const y = cy + Math.sin(a) * r;
      rock(i, x, y, s, spin * q);
      c.globalAlpha = Math.min(1, q * 6, (1 - q) * 6);
      c.font = fonts[e < 0.3 ? 0 : 1]!;
      c.lineWidth = 3 * dpr;
      c.strokeStyle = BG;
      const label = ASTEROID_LABELS[i % ASTEROID_LABELS.length]!;
      c.strokeText(label, x, y + s * 0.5);
      c.fillStyle = RED;
      c.fillText(label, x, y + s * 0.5);
      c.globalAlpha = 1;
    });
    const q = (p - MOMENTS.approach.nearMiss) / NEAR_SPAN;
    if (q > 0 && q < 1) {
      rock(1, w * (1.35 - 1.7 * q), cy + (q - 0.3) * h * 0.3, minD * (0.75 + 0.45 * Math.sin(q * Math.PI)), -2 * q);
    }
  }

  function flare(p: number, t: number) {
    const { retro, touchdown } = MOMENTS.landing;
    const k = Math.min(clamp01((p - retro) / 0.05), clamp01((touchdown + 0.12 - p) / 0.12));
    if (k <= 0 || !flareTex) return;
    const c = ctx!;
    const s = minD * (0.9 + 0.5 * k) * (0.92 + 0.08 * Math.sin(t * 55));
    c.globalCompositeOperation = "lighter";
    c.globalAlpha = k * 0.9;
    c.drawImage(flareTex, cx - s / 2, h - s * 0.35, s, s);
    c.globalAlpha = 1;
    c.globalCompositeOperation = "source-over";
  }

  function spawnDust() {
    dustN = DUST_COUNTS[tier];
    for (let i = 0; i < dustN; i++) {
      const x = cx + (Math.random() - 0.5) * w * 0.6;
      DX[i] = x;
      DY[i] = h * (0.82 + Math.random() * 0.18);
      DVX[i] = (x < cx ? -1 : 1) * (40 + 260 * Math.random()) * dpr;
      DVY[i] = -(60 + 240 * Math.random()) * dpr;
      DL[i] = DM[i] = 1.2 + 1.3 * Math.random();
    }
  }

  function dust(dt: number) {
    const c = ctx!;
    c.fillStyle = "#bdb6aa";
    for (let i = 0; i < dustN; i++) {
      const life = DL[i]! - dt;
      if (life + dt <= 0) continue;
      DL[i] = life;
      const vy = DVY[i]! + 160 * dpr * dt; // low gravity: the cloud hangs, then settles
      const vx = DVX[i]! * (1 - 1.5 * dt);
      DVY[i] = vy;
      DVX[i] = vx;
      const x = (DX[i] = DX[i]! + vx * dt);
      const y = (DY[i] = DY[i]! + vy * dt);
      const s = (1.5 + (i % 3)) * dpr;
      c.globalAlpha = Math.max(0, (0.7 * life) / DM[i]!);
      c.fillRect(x, y, s, s);
    }
    c.globalAlpha = 1;
  }

  function update(fr: Frame) {
    if (dead || !ctx) return;
    if (tier === "high") {
      slow = fr.dt * 1000 > SLOW_FRAME_MS ? slow + 1 : 0;
      if (slow >= SLOW_FRAMES) tier = "low";
    }
    const { phase: ph, p, t, mode } = fr;
    // A skip (or a stalled tab) jumps t: never simulate the gap, just land in the new state.
    const jumped = lastT >= 0 && (t < lastT || t - lastT > fr.dt + 0.25);
    const dt = jumped ? 0 : fr.dt;
    lastT = t;
    if (ph !== phase) {
      phase = ph;
      phaseT0 = t;
    }
    if (jumped) {
      dustN = 0;
      dustDone = ph === "reveal" || ph === "done" || (ph === "landing" && p >= MOMENTS.landing.touchdown);
    }
    if (ph === "done") return;
    if (mode === "reduced") {
      if (!still) {
        sky(1, 1);
        moon(0.6);
        still = true;
      }
      return;
    }
    still = false;

    switch (ph) {
      case "seatbelt":
        sky(0.45, 0.8 * clamp01(p * 1.6));
        break;
      case "cockpit":
        step(0.02 * dt);
        sky(1, 1);
        break;
      case "ignition":
        step((0.02 + 0.2 * p * p) * dt);
        sky(1, 1);
        break;
      case "warp": {
        const b = p < 0.9 ? (p / 0.9) ** 2 : 1 - (p - 0.9) * 4; // peaks at p=0.9
        step((0.12 + 2.3 * b) * dt);
        streaks(0.008 + 0.3 * p * p, 0.35 + 0.65 * b);
        break;
      }
      case "approach":
        step(0.03 * dt);
        sky(1, 1);
        moon(moonScale(p));
        if (mode === "full") {
          asteroids(p);
          const a = 1 - (t - phaseT0) / 0.25;
          if (a > 0) {
            ctx.globalAlpha = a;
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, w, h);
            ctx.globalAlpha = 1;
          }
        }
        break;
      case "landing": {
        const m = clamp01(p / 0.25); // the moon overfills the view, the horizon fades in
        const td = MOMENTS.landing.touchdown;
        if (m < 1) {
          sky(1, 1);
          moon(moonScale(1) * (1 + 5 * m * m));
        }
        const e = clamp01(p / td);
        landed(1 + 0.35 * (1 - (1 - e) * (1 - e)), m);
        flare(p, t);
        if (!dustDone && p >= td) {
          spawnDust();
          dustDone = true;
        }
        dust(dt);
        break;
      }
      case "reveal":
        if (mode === "full") landed(1.35, 1);
        else {
          sky(1, 1);
          moon(moonScale(1) + 0.2 * p);
        }
        dust(dt);
        ctx.globalAlpha = 0.4 * p;
        ctx.fillStyle = BG;
        ctx.fillRect(0, 0, w, h);
        ctx.globalAlpha = 1;
        break;
    }
  }

  function destroy() {
    dead = true;
    ctx?.clearRect(0, 0, canvas.width, canvas.height);
    for (const tex of [moonTex, groundTex, flareTex, ...rockTex]) if (tex) tex.width = tex.height = 0;
  }

  resize();
  return { update, resize, destroy, quality: () => tier };
}
