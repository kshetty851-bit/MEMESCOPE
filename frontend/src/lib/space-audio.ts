/**
 * SPACE MUSIC, SYNTHESISED RATHER THAN SHIPPED.
 *
 * There is no audio file here and there deliberately isn't one. A few minutes
 * of ambient audio is several megabytes, it would have to be licensed, and
 * this project spent a whole day getting a 38GB disk back under control. The
 * Web Audio API can make this sound directly, so the entire soundtrack costs a
 * few kilobytes of JavaScript and nothing on disk.
 *
 * WHAT IT PLAYS — and what it used to
 *
 * This was a continuous five-voice drone. Karthik didn't like it, and asked
 * for sparse and quiet instead: mostly silence, with occasional soft bell
 * tones that ring out and fade. So there is now NO CONTINUOUS TONE AT ALL. A
 * single note is struck every few seconds, left to decay for as long as eight
 * seconds through a generated reverb, and then nothing until the next one.
 *
 * If you are tempted to add a pad back underneath "just to fill the gaps":
 * the gaps are the request. Silence is the majority of this piece.
 *
 * A struck metal tone is not a sine wave — its partials are inharmonic, which
 * is exactly what makes a bell sound like a bell rather than an organ. The
 * ratios in `PARTIALS` are the usual approximation, with the higher partials
 * both quieter and shorter-lived, because real bells shed their upper
 * partials first.
 *
 * WHY IT NEVER STARTS ON ITS OWN
 *
 * Every browser blocks audio until a real user gesture, and a site that plays
 * sound at someone unasked deserves the block. `start()` must be called from
 * a click handler. That is also why nothing here is persisted: a remembered
 * "on" could not be honoured on the next visit without a gesture anyway.
 */

/** The scale struck notes are drawn from: A minor pentatonic, in Hz. */
export const NOTES: readonly number[] = [
  220.0, // A3
  261.63, // C4
  293.66, // D4
  329.63, // E4
  392.0, // G4
  440.0, // A4
  523.25, // C5
];

/**
 * One partial of a struck tone: its frequency as a multiple of the note, how
 * loud it starts, and how long it rings relative to the note's decay.
 *
 * The inharmonic ratios are what make this a bell. Equal-tempered multiples
 * (1, 2, 3) would give an organ pipe.
 */
export const PARTIALS: readonly { ratio: number; gain: number; decay: number }[] = [
  { ratio: 0.5, gain: 0.35, decay: 1.0 }, // hum tone, rings longest
  { ratio: 1.0, gain: 1.0, decay: 0.85 }, // the note you hear
  { ratio: 2.76, gain: 0.28, decay: 0.45 },
  { ratio: 5.4, gain: 0.11, decay: 0.22 },
];

/** How long the fundamental takes to fall away, in seconds. */
export const DECAY_SECONDS = 8;

/** Silence between strikes, in seconds. The gaps are the point. */
export const GAP_MIN_SECONDS = 5;
export const GAP_MAX_SECONDS = 13;

/**
 * The two fades are NOT the same length, and that asymmetry is the point.
 *
 * Both were 2.5s. Fading in over 2.5s is fine; fading OUT over 2.5s is a
 * broken button — Karthik pressed off, kept hearing music, and reported it as
 * still playing. Measured: 2.0s after the click it was still at RMS 0.011,
 * plainly audible. Off has to sound like off.
 */
export const FADE_IN_SECONDS = 1.2;
export const FADE_OUT_SECONDS = 0.3;

/**
 * Ceiling on the master gain. Lower than the drone's was: these are transients
 * with a lot of high content, so they carry further than a steady tone at the
 * same nominal level, and "very quiet" was the request.
 */
export const MASTER_GAIN = 0.11;

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
 * A long synthetic impulse response: white noise under an exponential decay,
 * which is the standard cheap way to get a plausible reverb tail without
 * shipping one. Long here on purpose — the reverb is most of what fills the
 * space between strikes.
 */
export function impulseResponse(ctx: BaseAudioContext, seconds = 5, decay = 2.2): AudioBuffer {
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

/** Seconds until the next strike. Random, so no rhythm emerges. */
export function nextGap(random: () => number = Math.random): number {
  return GAP_MIN_SECONDS + random() * (GAP_MAX_SECONDS - GAP_MIN_SECONDS);
}

/**
 * One note from the scale. The clamp and the fallback are for
 * `noUncheckedIndexedAccess`, which types every array read as possibly
 * undefined — and is right to, since `random()` returning exactly 1 would
 * index past the end.
 */
export function pickNote(random: () => number = Math.random): number {
  const i = Math.min(NOTES.length - 1, Math.floor(random() * NOTES.length));
  return NOTES[i] ?? 440;
}

export interface SpaceAudio {
  /** Must be called from a user gesture. Resumes and fades in. */
  start(): Promise<void>;
  /** Fades out, stops scheduling, and suspends. start() is cheap again. */
  stop(): void;
  /** Tears the whole thing down. After this the instance is dead. */
  dispose(): void;
}

export function createSpaceAudio(ctx: AudioContext): SpaceAudio {
  const master = ctx.createGain();
  master.gain.value = 0;
  master.connect(ctx.destination);

  // Strikes go to both the dry bus and a long reverb. The reverb is what makes
  // the silence sound like a room rather than a mute.
  const dry = ctx.createGain();
  dry.gain.value = 0.55;
  dry.connect(master);

  const reverb = ctx.createConvolver();
  reverb.buffer = impulseResponse(ctx);
  const wet = ctx.createGain();
  wet.gain.value = 0.8;
  reverb.connect(wet);
  wet.connect(master);

  // Takes the glassiest edge off the upper partials.
  const tone = ctx.createBiquadFilter();
  tone.type = "lowpass";
  tone.frequency.value = 2600;
  tone.connect(dry);
  tone.connect(reverb);

  let disposed = false;
  let timer: number | null = null;
  // Every start/stop takes a ticket. A pending suspend only fires if it still
  // holds the current one — otherwise turning the sound back on during a
  // fade-out gets silently suspended a moment later by the old timer, which
  // looks exactly like the button failing.
  let ticket = 0;

  /** One struck note: a stack of decaying inharmonic partials. */
  function strike(hz: number): void {
    const now = ctx.currentTime;
    for (const partial of PARTIALS) {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.value = hz * partial.ratio;

      const env = ctx.createGain();
      const decay = DECAY_SECONDS * partial.decay;
      // Fast but not instant: a true step would click.
      env.gain.setValueAtTime(0, now);
      env.gain.linearRampToValueAtTime(partial.gain, now + 0.006);
      // Exponential, because that is how a struck object actually decays. It
      // cannot reach zero, so it is cut to zero once inaudible.
      env.gain.exponentialRampToValueAtTime(0.0001, now + decay);
      env.gain.setValueAtTime(0, now + decay + 0.01);

      osc.connect(env);
      env.connect(tone);
      osc.start(now);
      // Stopped and dropped: nothing accumulates between strikes.
      osc.stop(now + decay + 0.05);
    }
  }

  function scheduleNext(): void {
    if (disposed) return;
    timer = window.setTimeout(() => {
      if (disposed) return;
      strike(pickNote());
      scheduleNext();
    }, nextGap() * 1000);
  }

  function ramp(to: number, seconds: number): void {
    const now = ctx.currentTime;
    // Pin the curve to where the gain actually is, or a toggle mid-fade jumps.
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(master.gain.value, now);
    master.gain.linearRampToValueAtTime(to, now + seconds);
  }

  function clearTimer(): void {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  return {
    async start() {
      if (disposed) return;
      ticket += 1;
      // Autoplay policy: the context starts suspended and only a gesture-borne
      // resume() will run it.
      if (ctx.state !== "running") await ctx.resume();
      ramp(MASTER_GAIN, FADE_IN_SECONDS);
      clearTimer();
      // One note straight away, so pressing the button is answered rather than
      // met with up to thirteen seconds of nothing.
      strike(pickNote());
      scheduleNext();
    },
    stop() {
      if (disposed) return;
      ticket += 1;
      const mine = ticket;
      clearTimer();
      ramp(0, FADE_OUT_SECONDS);
      // Suspend only after the fade has finished, or it cuts itself off.
      window.setTimeout(() => {
        if (!disposed && mine === ticket && ctx.state === "running") void ctx.suspend();
      }, FADE_OUT_SECONDS * 1000 + 80);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      clearTimer();
      void ctx.close();
    },
  };
}
