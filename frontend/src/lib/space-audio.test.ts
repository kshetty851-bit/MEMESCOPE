import { describe, expect, it } from "vitest";

import {
  FADE_IN_SECONDS,
  FADE_OUT_SECONDS,
  MASTER_GAIN,
  SWELL_BASE,
  SWELL_DEPTH,
  VOICES,
  beatHz,
  impulseResponse,
} from "./space-audio";

/**
 * The two things here that can silently stop being true: the swell periods
 * drifting into a common factor (which makes the pad audibly loop, the one
 * thing ambient music must not do), and the mix creeping up until background
 * music is foreground noise.
 */

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

describe("the drone", () => {
  it("gives every voice a swell period coprime with the others", () => {
    const periods = VOICES.map((v) => v.periodSeconds);
    expect(new Set(periods).size).toBe(periods.length);
    for (let i = 0; i < periods.length; i += 1) {
      for (let j = i + 1; j < periods.length; j += 1) {
        expect(gcd(periods[i], periods[j])).toBe(1);
      }
    }
  });

  it("stays quiet enough to sit behind the page", () => {
    expect(MASTER_GAIN).toBeLessThanOrEqual(0.25);
    // Even summed flat, the voices must not clip the master before it.
    const summed = VOICES.reduce((acc, v) => acc + v.gain, 0);
    expect(summed * MASTER_GAIN).toBeLessThan(1);
  });

  it("fades out fast enough that off sounds like off", () => {
    // Both fades were 2.5s and the off button was reported as not working:
    // 2.0s after the click the drone was still plainly audible. Out must be
    // near-immediate; in may take its time.
    expect(FADE_OUT_SECONDS).toBeLessThanOrEqual(0.5);
    // ...but not so abrupt that cutting a 55Hz drone thuds.
    expect(FADE_OUT_SECONDS).toBeGreaterThanOrEqual(0.15);
    expect(FADE_IN_SECONDS).toBeGreaterThan(FADE_OUT_SECONDS);
  });

  it("swells without hollowing out at the trough", () => {
    // At 0.55/0.45 a voice fell to a tenth of nominal and the pad went thin
    // for seconds, because the root carries most of the energy. The trough
    // must stay at least half of nominal, and the swell must still move.
    const trough = SWELL_BASE - SWELL_DEPTH;
    const peak = SWELL_BASE + SWELL_DEPTH;
    expect(trough).toBeGreaterThanOrEqual(0.45);
    expect(peak).toBeLessThanOrEqual(1);
    expect(SWELL_DEPTH).toBeGreaterThan(0.1); // still breathes
  });

  it("gives every voice its own beat rate, so they cannot null together", () => {
    // The bug this replaces: a fixed hertz detune gave all five voices the
    // same beat rate and the same start phase, so the whole pad fell to
    // near-silence every ~8 seconds. Measured RMS 0.051 -> 0.004 with the
    // master gain still at 0.16. Cents scale with pitch, so the rates differ.
    const rates = VOICES.map((v) => beatHz(v.hz));
    for (const r of rates) {
      expect(r).toBeGreaterThan(0.05); // audible movement
      expect(r).toBeLessThan(4); // a beat, not a tremolo
    }
    for (let i = 0; i < rates.length; i += 1) {
      for (let j = i + 1; j < rates.length; j += 1) {
        // Comfortably distinct, not merely unequal by a rounding error.
        expect(Math.abs(rates[i] - rates[j])).toBeGreaterThan(0.02);
      }
    }
  });

  it("is a chord, not a cluster — every voice a distinct pitch", () => {
    const hz = VOICES.map((v) => v.hz);
    expect(new Set(hz).size).toBe(hz.length);
    // Nothing subsonic, nothing shrill.
    for (const f of hz) {
      expect(f).toBeGreaterThan(30);
      expect(f).toBeLessThan(2000);
    }
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

    const buffer = impulseResponse(ctx, 1, 2.4);
    const data = buffer.getChannelData(0);

    const head = Math.max(...Array.from(data.slice(0, 100), Math.abs));
    const tail = Math.max(...Array.from(data.slice(-100), Math.abs));
    expect(head).toBeGreaterThan(0.1);
    expect(tail).toBeLessThan(0.05);
  });
});
