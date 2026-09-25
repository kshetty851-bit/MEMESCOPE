/**
 * THE MOON INTRO SOUNDBOARD — every sound is synthesised (WebAudio), no files.
 *
 * No AudioContext exists until `unlock()`, which must run inside a user
 * gesture; before that everything is a silent no-op (the latest throttle is
 * remembered). Every one-shot node stops itself and disconnects on `ended`,
 * and all noise comes from one shared 1s buffer.
 */

export type SoundName = "click" | "switch" | "beep" | "whoosh" | "alarm" | "thud" | "static";

export type Soundboard = {
  play(name: SoundName): void;
  /** Engine rumble: looped; 0 stops it (with a short fade), 0..1 sets level AND pitch (pitch follows throttle). */
  setThrottle(level: number): void;
  setMuted(muted: boolean): void;
  /** Create/resume the AudioContext. Call ONLY from a user-gesture handler. Safe to call repeatedly. */
  unlock(): void;
  /** Stop everything and close the context. */
  destroy(): void;
};

const MASTER = 0.7;
const SILENT = 0.0001;

type Engine = { gain: GainNode; filter: BiquadFilterNode; oscs: OscillatorNode[]; sources: AudioScheduledSourceNode[] };

function audioContextClass(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
}

export function createSoundboard(): Soundboard {
  let ctx: AudioContext | null = null;
  let master: GainNode | null = null;
  let noise: AudioBuffer | null = null;
  let muted = false;
  let throttle = 0;
  let engine: Engine | null = null;
  let destroyed = false;

  /** Disconnect the whole chain once its source has finished. */
  function cleanup(source: AudioScheduledSourceNode, nodes: AudioNode[]) {
    source.onended = () => nodes.forEach((n) => n.disconnect());
  }

  /** Attack to `vol`, then decay to silence at `at + dur`. */
  function envelope(gain: GainNode, at: number, dur: number, vol: number, attack = 0.003) {
    gain.gain.setValueAtTime(SILENT, at);
    gain.gain.exponentialRampToValueAtTime(vol, at + attack);
    gain.gain.exponentialRampToValueAtTime(SILENT, at + dur);
  }

  function tone(freq: number, at: number, dur: number, vol: number, type: OscillatorType, glideTo?: number) {
    if (!ctx || !master) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, at);
    if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, at + dur);
    envelope(gain, at, dur, vol);
    osc.connect(gain).connect(master);
    cleanup(osc, [osc, gain]);
    osc.start(at);
    osc.stop(at + dur + 0.02);
  }

  /** A filtered slice of the shared noise buffer; returns the filter for sweeps. */
  function burst(at: number, dur: number, vol: number, type: BiquadFilterType, freq: number, q = 1, attack?: number) {
    if (!ctx || !master || !noise) return null;
    const src = ctx.createBufferSource();
    src.buffer = noise;
    src.loop = true;
    const filter = ctx.createBiquadFilter();
    filter.type = type;
    filter.frequency.setValueAtTime(freq, at);
    filter.Q.value = q;
    const gain = ctx.createGain();
    envelope(gain, at, dur, vol, attack);
    src.connect(filter).connect(gain).connect(master);
    cleanup(src, [src, filter, gain]);
    // Random offset so repeated bursts don't sound identical.
    src.start(at, Math.random() * 0.5);
    src.stop(at + dur + 0.02);
    return filter;
  }

  const sounds: Record<SoundName, (t: number) => void> = {
    // Seatbelt buckle: two bright metallic snaps.
    click(t) {
      for (const at of [t, t + 0.07]) {
        burst(at, 0.03, 0.5, "highpass", 4000);
        tone(3200, at, 0.04, 0.12, "triangle", 2200);
      }
    },
    // Toggle clack: a mid knock with a falling tick.
    switch(t) {
      burst(t, 0.04, 0.4, "bandpass", 1800, 3);
      tone(900, t, 0.035, 0.1, "square", 500);
    },
    beep(t) {
      tone(880, t, 0.12, 0.12, "square");
    },
    // Warp: band-passed noise sweeps up, then back down.
    whoosh(t) {
      const f = burst(t, 1.2, 0.4, "bandpass", 200, 1.4, 0.5);
      f?.frequency.exponentialRampToValueAtTime(3000, t + 0.6);
      f?.frequency.exponentialRampToValueAtTime(400, t + 1.2);
    },
    // Hull breach: two tones alternating, sawtooth for bite.
    alarm(t) {
      [660, 880, 660, 880].forEach((f, i) => tone(f, t + i * 0.15, 0.14, 0.08, "sawtooth"));
    },
    // Landing: a low sine drop plus a dusty puff.
    thud(t) {
      tone(120, t, 0.45, 0.6, "sine", 40);
      burst(t, 0.3, 0.3, "lowpass", 400, 0.7);
    },
    // Radio: a short band-passed crackle.
    static(t) {
      burst(t, 0.15, 0.25, "bandpass", 1500, 0.8);
    },
  };

  function startEngine() {
    const c = ctx;
    if (!c || !master || !noise) return;
    const gain = c.createGain();
    gain.gain.value = 0;
    const filter = c.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 150;
    const oscs = (["sawtooth", "triangle"] as const).map((type, i) => {
      const osc = c.createOscillator();
      osc.type = type;
      osc.frequency.value = 45;
      osc.detune.value = i ? 9 : -9;
      osc.connect(filter);
      return osc;
    });
    const hiss = c.createBufferSource();
    hiss.buffer = noise;
    hiss.loop = true;
    const hissGain = c.createGain();
    hissGain.gain.value = 0.15;
    hiss.connect(hissGain).connect(filter);
    filter.connect(gain).connect(master);
    const sources = [...oscs, hiss];
    const nodes: AudioNode[] = [...sources, hissGain, filter, gain];
    cleanup(hiss, nodes);
    sources.forEach((s) => s.start());
    engine = { gain, filter, oscs, sources };
  }

  function stopEngine(fade: number) {
    if (!ctx || !engine) return;
    const now = ctx.currentTime;
    engine.gain.gain.cancelScheduledValues(now);
    engine.gain.gain.setTargetAtTime(0, now, fade / 5);
    engine.sources.forEach((s) => s.stop(now + fade));
    engine = null;
  }

  function applyThrottle() {
    if (!ctx) return;
    if (throttle <= 0) return stopEngine(0.4);
    if (!engine) startEngine();
    if (!engine) return;
    const now = ctx.currentTime;
    engine.oscs.forEach((o) => o.frequency.setTargetAtTime(45 + 45 * throttle, now, 0.15));
    engine.filter.frequency.setTargetAtTime(150 + 350 * throttle, now, 0.15);
    engine.gain.gain.setTargetAtTime(0.35 * throttle, now, 0.1);
  }

  return {
    play(name) {
      if (!ctx || muted) return;
      sounds[name](ctx.currentTime);
    },
    setThrottle(level) {
      throttle = Math.min(1, Math.max(0, Number.isFinite(level) ? level : 0));
      applyThrottle();
    },
    setMuted(next) {
      muted = next;
      if (ctx && master) master.gain.setTargetAtTime(muted ? 0 : MASTER, ctx.currentTime, 0.04);
    },
    unlock() {
      if (destroyed) return;
      if (ctx) {
        if (ctx.state === "suspended") void ctx.resume().catch(() => {});
        return;
      }
      const Ctx = audioContextClass();
      if (!Ctx) return;
      ctx = new Ctx();
      master = ctx.createGain();
      master.gain.value = muted ? 0 : MASTER;
      master.connect(ctx.destination);
      noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
      void ctx.resume().catch(() => {});
      applyThrottle();
    },
    destroy() {
      destroyed = true;
      stopEngine(0);
      if (ctx) void ctx.close().catch(() => {});
      ctx = master = noise = null;
    },
  };
}
