/**
 * SPACE MUSIC, SYNTHESISED RATHER THAN SHIPPED.
 *
 * There is no audio file here and there deliberately isn't one. A few minutes
 * of ambient pad is several megabytes, it would have to be licensed, and this
 * project spent a whole day getting a 38GB disk back under control. The Web
 * Audio API can make this sound directly out of oscillators, so the entire
 * soundtrack costs a few kilobytes of JavaScript and nothing on disk.
 *
 * WHAT IT PLAYS
 *
 * A drone in A, and nothing else: a low root, a fifth, and three quiet upper
 * partials from the pentatonic scale, each swelling on its own slow cycle.
 * The cycle lengths are mutually prime (17, 23, 29, 31, 37 seconds), so the
 * voices drift in and out of alignment and the pattern does not audibly
 * repeat — the whole point of ambient music, and much cheaper than a long
 * sample. Two oscillators per voice detuned by a fraction of a hertz give the
 * slow beating that makes a synthesised pad sound wide rather than sterile.
 *
 * WHY IT NEVER STARTS ON ITS OWN
 *
 * Every browser blocks audio until a real user gesture, and a site that plays
 * sound at someone unasked deserves the block. `start()` must be called from
 * a click handler. That is also why nothing here is persisted: a remembered
 * "on" could not be honoured on the next visit without a gesture anyway, so
 * remembering it would only create the expectation it cannot meet.
 */

/** One voice: a frequency in Hz, how loud it sits, and its swell period. */
export interface Voice {
  readonly hz: number;
  readonly gain: number;
  readonly periodSeconds: number;
  readonly type: OscillatorType;
}

/**
 * A minor pentatonic drone on A. Root and fifth carry the weight; the three
 * upper voices are quiet enough to colour rather than play a tune.
 *
 * Periods are mutually prime ON PURPOSE — see the file docstring. If you edit
 * these, keep them coprime or the pad starts to loop audibly.
 */
export const VOICES: readonly Voice[] = [
  { hz: 55.0, gain: 0.5, periodSeconds: 31, type: "sine" }, // A1, the floor
  { hz: 82.41, gain: 0.28, periodSeconds: 37, type: "sine" }, // E2, the fifth
  { hz: 220.0, gain: 0.1, periodSeconds: 17, type: "triangle" }, // A3
  { hz: 329.63, gain: 0.07, periodSeconds: 23, type: "sine" }, // E4
  { hz: 493.88, gain: 0.05, periodSeconds: 29, type: "sine" }, // B4
];

/**
 * Detune between a voice's two oscillators, in CENTS rather than hertz.
 *
 * This is not a stylistic choice, it is the fix for a bug worth remembering.
 * A fixed hertz offset gives every voice the SAME beat rate, and since all the
 * oscillators start on the same `start()` they also share a phase — so all
 * five voices reached their destructive null together and the entire pad
 * dropped to near silence every ~8 seconds. Measured in the browser: RMS fell
 * from 0.051 to 0.004 with the master gain still wide open at 0.16.
 *
 * Cents scale with pitch, the way real detuning does, so each voice beats at
 * its own rate (~0.13 Hz on the root, ~1.1 Hz on the top voice) and the sum
 * never nulls.
 */
const DETUNE_CENTS = 2.5;

/**
 * The two oscillators of a pair are deliberately NOT equal in level. Equal
 * amplitudes cancel completely at the null; 62/38 leaves a quarter of the
 * amplitude standing, which is a gentle dip instead of a hole.
 */
const PAIR_MIX = [0.62, 0.38] as const;

/** Beat frequency produced by `DETUNE_CENTS` at a given pitch, in Hz. */
export function beatHz(hz: number, cents: number = DETUNE_CENTS): number {
  return hz * (2 ** (cents / 1200) - 2 ** (-cents / 1200));
}

/**
 * How deep each voice's slow swell goes. A voice sits at `SWELL_BASE` and its
 * LFO adds up to `SWELL_DEPTH`, so its level travels between base − depth and
 * base + depth.
 *
 * These were 0.55/0.45 — a swing down to a tenth of nominal, or 20dB. Measured
 * in the browser, that made the whole pad go thin for seconds at a time,
 * because the root voice carries most of the energy and takes the rest down
 * with it. 0.75/0.25 halves the level at the trough instead of gutting it: the
 * pad still breathes, it just never hollows out.
 */
export const SWELL_BASE = 0.75;
export const SWELL_DEPTH = 0.25;

/** Fade length. Long, because an abrupt gain change is an audible click. */
export const FADE_SECONDS = 2.5;

/** Ceiling on the master gain. Background music, not a foreground event. */
export const MASTER_GAIN = 0.16;

type Ctor = typeof AudioContext;

/**
 * Safari still only has the prefixed constructor.
 *
 * The parameter is `Window & typeof globalThis`, not `Window`: the global
 * constructors hang off `globalThis`, and the bare `Window` interface does not
 * declare `AudioContext` at all — which `tsc` only complains about once
 * `next build` runs it.
 */
export function audioContextCtor(win: Window & typeof globalThis = window): Ctor | null {
  const w = win as typeof win & { webkitAudioContext?: Ctor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

/**
 * A short synthetic impulse response: white noise under an exponential decay,
 * which is the standard cheap way to get a plausible reverb tail without
 * shipping one. `decay` shapes how quickly the room dies away.
 */
export function impulseResponse(ctx: BaseAudioContext, seconds = 3.5, decay = 2.4): AudioBuffer {
  const rate = ctx.sampleRate;
  const length = Math.max(1, Math.floor(rate * seconds));
  const buffer = ctx.createBuffer(2, length, rate);
  for (let channel = 0; channel < 2; channel += 1) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i += 1) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** decay;
    }
  }
  return buffer;
}

export interface SpaceAudio {
  /** Must be called from a user gesture. Resumes and fades in. */
  start(): Promise<void>;
  /** Fades out and suspends. The graph is kept, so start() is cheap again. */
  stop(): void;
  /** Tears the whole thing down. After this the instance is dead. */
  dispose(): void;
}

/**
 * Build the graph once and keep it. Starting and stopping only moves the
 * master gain and suspends the context — oscillators are never recreated,
 * because an `OscillatorNode` cannot be restarted after `stop()` and
 * rebuilding the graph on every toggle is how you get a click and a leak.
 */
export function createSpaceAudio(ctx: AudioContext): SpaceAudio {
  const master = ctx.createGain();
  master.gain.value = 0;

  // Rolls the top off the oscillators so the pad is warm rather than glassy.
  const tone = ctx.createBiquadFilter();
  tone.type = "lowpass";
  tone.frequency.value = 900;
  tone.Q.value = 0.6;

  const reverb = ctx.createConvolver();
  reverb.buffer = impulseResponse(ctx);
  const wet = ctx.createGain();
  wet.gain.value = 0.55;

  tone.connect(master);
  tone.connect(reverb);
  reverb.connect(wet);
  wet.connect(master);
  master.connect(ctx.destination);

  // A very slow sweep of the filter, so the timbre breathes.
  const sweep = ctx.createOscillator();
  sweep.frequency.value = 1 / 41; // once every 41s — coprime with the voices
  const sweepDepth = ctx.createGain();
  sweepDepth.gain.value = 260;
  sweep.connect(sweepDepth);
  sweepDepth.connect(tone.frequency);
  sweep.start();

  const started: OscillatorNode[] = [sweep];

  for (const voice of VOICES) {
    const swell = ctx.createGain();
    swell.gain.value = voice.gain * SWELL_BASE;
    swell.connect(tone);

    // Each voice breathes on its own period, none of them together.
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 1 / voice.periodSeconds;
    const lfoDepth = ctx.createGain();
    lfoDepth.gain.value = voice.gain * SWELL_DEPTH;
    lfo.connect(lfoDepth);
    lfoDepth.connect(swell.gain);
    lfo.start();
    started.push(lfo);

    PAIR_MIX.forEach((mix, i) => {
      const osc = ctx.createOscillator();
      osc.type = voice.type;
      osc.frequency.value = voice.hz;
      osc.detune.value = i === 0 ? -DETUNE_CENTS : DETUNE_CENTS;

      // The unequal half of the pair, so a null is a dip and not a hole.
      const trim = ctx.createGain();
      trim.gain.value = mix;
      osc.connect(trim);
      trim.connect(swell);

      osc.start();
      started.push(osc);
    });
  }

  let disposed = false;

  function ramp(to: number): void {
    const now = ctx.currentTime;
    // Pin the curve to where the gain actually is, or a toggle mid-fade jumps.
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(master.gain.value, now);
    master.gain.linearRampToValueAtTime(to, now + FADE_SECONDS);
  }

  return {
    async start() {
      if (disposed) return;
      // Autoplay policy: the context starts suspended and only a gesture-borne
      // resume() will run it.
      if (ctx.state !== "running") await ctx.resume();
      ramp(MASTER_GAIN);
    },
    stop() {
      if (disposed) return;
      ramp(0);
      // Suspend only after the fade has finished, or it cuts itself off.
      window.setTimeout(() => {
        if (!disposed && ctx.state === "running") void ctx.suspend();
      }, FADE_SECONDS * 1000 + 100);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const node of started) {
        try {
          node.stop();
        } catch {
          // Already stopped; nothing to undo.
        }
      }
      void ctx.close();
    },
  };
}
