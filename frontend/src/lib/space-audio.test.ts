import { describe, expect, it } from "vitest";

import {
  DECAY_SECONDS,
  FADE_IN_SECONDS,
  FADE_OUT_SECONDS,
  GAP_MAX_SECONDS,
  GAP_MIN_SECONDS,
  MASTER_GAIN,
  NOTES,
  PARTIALS,
  impulseResponse,
  nextGap,
  pickNote,
} from "./space-audio";

/**
 * The brief was "sparse and quiet": mostly silence, occasional soft tones.
 * The way that decays back into the thing it replaced is by the gaps closing
 * up or the level creeping — so those are what is asserted here. The sound
 * itself is measured in a real browser, not in jsdom, which has no Web Audio.
 */

describe("the strikes", () => {
  it("leaves real silence between notes", () => {
    // A note is inaudible well before its nominal decay ends, so a gap
    // shorter than the decay still reads as space. What must not happen is
    // strikes arriving so often that they overlap into a continuous bed.
    expect(GAP_MIN_SECONDS).toBeGreaterThanOrEqual(4);
    expect(GAP_MAX_SECONDS).toBeGreaterThan(GAP_MIN_SECONDS);
  });

  it("never falls into a rhythm", () => {
    const gaps = new Set<number>();
    for (let i = 0; i < 200; i += 1) gaps.add(nextGap());
    // Random, not a fixed interval dressed up as one.
    expect(gaps.size).toBeGreaterThan(150);
    for (const g of gaps) {
      expect(g).toBeGreaterThanOrEqual(GAP_MIN_SECONDS);
      expect(g).toBeLessThanOrEqual(GAP_MAX_SECONDS);
    }
  });

  it("uses the whole range it is given", () => {
    expect(nextGap(() => 0)).toBeCloseTo(GAP_MIN_SECONDS);
    expect(nextGap(() => 1)).toBeCloseTo(GAP_MAX_SECONDS);
  });

  it("rings long enough to fade rather than stop", () => {
    expect(DECAY_SECONDS).toBeGreaterThanOrEqual(4);
  });

  it("is a bell, not an organ — the partials are inharmonic", () => {
    const ratios = PARTIALS.map((p) => p.ratio);
    // At least one partial must be a non-integer multiple, or this is a
    // harmonic stack and sounds like a pipe.
    expect(ratios.some((r) => Math.abs(r - Math.round(r)) > 0.1)).toBe(true);
    // Upper partials must be quieter AND shorter, the way a real bell sheds
    // them; otherwise the tone stays bright all the way down and rings harsh.
    const upper = PARTIALS.filter((p) => p.ratio > 1);
    const fundamental = PARTIALS.find((p) => p.ratio === 1)!;
    for (const p of upper) {
      expect(p.gain).toBeLessThan(fundamental.gain);
      expect(p.decay).toBeLessThan(fundamental.decay);
    }
  });

  it("always picks a real note, including at the ends of the range", () => {
    // `random()` may return exactly 0, and in principle 1 — the second would
    // index past the array and hand an `undefined` frequency to an oscillator,
    // which is a silent strike rather than a crash, and so would go unnoticed.
    expect(pickNote(() => 0)).toBe(NOTES[0]);
    expect(pickNote(() => 1)).toBe(NOTES[NOTES.length - 1]);
    expect(pickNote(() => 0.999999)).toBe(NOTES[NOTES.length - 1]);
    for (let i = 0; i < 100; i += 1) {
      expect(NOTES).toContain(pickNote());
    }
  });

  it("draws from a scale, so no two notes clash", () => {
    expect(new Set(NOTES).size).toBe(NOTES.length);
    for (const hz of NOTES) {
      expect(hz).toBeGreaterThan(100);
      expect(hz).toBeLessThan(1200);
    }
  });
});

describe("the mix", () => {
  it("stays quiet enough to sit behind the page", () => {
    expect(MASTER_GAIN).toBeLessThanOrEqual(0.15);
    // Even with every partial at full tilt, the strike must not clip.
    const summed = PARTIALS.reduce((acc, p) => acc + p.gain, 0);
    expect(summed * MASTER_GAIN).toBeLessThan(1);
  });

  it("fades out fast enough that off sounds like off", () => {
    // Both fades were 2.5s and the off button was reported as not working:
    // 2.0s after the click the sound was still plainly audible.
    expect(FADE_OUT_SECONDS).toBeLessThanOrEqual(0.5);
    // ...but not so abrupt that it clicks.
    expect(FADE_OUT_SECONDS).toBeGreaterThanOrEqual(0.15);
    expect(FADE_IN_SECONDS).toBeGreaterThan(FADE_OUT_SECONDS);
  });
});

describe("impulseResponse", () => {
  it("decays to near silence, so the tail does not ring forever", () => {
    // A stub context: only what the function actually touches.
    const ctx = {
      sampleRate: 8000,
      createBuffer: (channels: number, length: number) => {
        const data = Array.from({ length: channels }, () => new Float32Array(length));
        return {
          length,
          numberOfChannels: channels,
          getChannelData: (i: number) => data[i],
        };
      },
    } as unknown as BaseAudioContext;

    const buffer = impulseResponse(ctx, 1, 2.2);
    const data = buffer.getChannelData(0);

    const head = Math.max(...Array.from(data.slice(0, 100), Math.abs));
    const tail = Math.max(...Array.from(data.slice(-100), Math.abs));
    expect(head).toBeGreaterThan(0.1);
    expect(tail).toBeLessThan(0.05);
  });
});
