import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createSoundboard, type SoundName } from "./soundboard";

/** A fake AudioContext that records what the board builds and starts. */
const log = { contexts: 0, nodes: 0, started: 0, stopped: 0, closed: 0 };

function param() {
  return {
    value: 0,
    setValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    setTargetAtTime: vi.fn(),
    cancelScheduledValues: vi.fn(),
  };
}

function node() {
  log.nodes += 1;
  return {
    type: "",
    buffer: null as unknown,
    loop: false,
    onended: null as unknown,
    gain: param(),
    frequency: param(),
    detune: param(),
    Q: param(),
    connect: vi.fn((target: unknown) => target),
    disconnect: vi.fn(),
    start: vi.fn(() => void (log.started += 1)),
    stop: vi.fn(() => void (log.stopped += 1)),
  };
}

class FakeAudioContext {
  currentTime = 0;
  sampleRate = 8000;
  state = "running";
  destination = {};
  constructor() {
    log.contexts += 1;
  }
  createGain = node;
  createOscillator = node;
  createBiquadFilter = node;
  createBufferSource = node;
  createBuffer(_channels: number, length: number) {
    return { getChannelData: () => new Float32Array(length) };
  }
  resume = vi.fn(() => Promise.resolve());
  close = vi.fn(() => {
    log.closed += 1;
    return Promise.resolve();
  });
}

const SOUNDS: SoundName[] = ["click", "switch", "beep", "whoosh", "alarm", "thud", "static"];

beforeEach(() => {
  Object.assign(log, { contexts: 0, nodes: 0, started: 0, stopped: 0, closed: 0 });
  vi.stubGlobal("AudioContext", FakeAudioContext);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createSoundboard", () => {
  it("creates no AudioContext until unlock, and play/throttle are no-ops before it", () => {
    const board = createSoundboard();
    board.play("click");
    board.setThrottle(0.5);
    expect(log.contexts).toBe(0);
    expect(log.nodes).toBe(0);
  });

  it("unlock twice creates one context", () => {
    const board = createSoundboard();
    board.unlock();
    board.unlock();
    expect(log.contexts).toBe(1);
  });

  it.each(SOUNDS)("%s schedules and starts nodes after unlock", (name) => {
    const board = createSoundboard();
    board.unlock();
    const before = { nodes: log.nodes, started: log.started, stopped: log.stopped };
    board.play(name);
    expect(log.nodes).toBeGreaterThan(before.nodes);
    expect(log.started).toBeGreaterThan(before.started);
    // Every one-shot source is scheduled to stop, so nothing leaks.
    expect(log.stopped - before.stopped).toBe(log.started - before.started);
  });

  it("muted play schedules nothing", () => {
    const board = createSoundboard();
    board.unlock();
    board.setMuted(true);
    const nodes = log.nodes;
    SOUNDS.forEach((s) => board.play(s));
    expect(log.nodes).toBe(nodes);
  });

  it("throttle starts the rumble and 0 stops it", () => {
    const board = createSoundboard();
    board.unlock();
    board.setThrottle(0.5);
    expect(log.started).toBe(3); // two oscillators + hiss
    board.setThrottle(0.8); // retunes, does not restart
    expect(log.started).toBe(3);
    board.setThrottle(0);
    expect(log.stopped).toBe(3);
  });

  it("a throttle set before unlock starts the rumble on unlock", () => {
    const board = createSoundboard();
    board.setThrottle(0.5);
    board.unlock();
    expect(log.started).toBe(3);
  });

  it("destroy closes the context and later calls are no-ops", () => {
    const board = createSoundboard();
    board.unlock();
    board.setThrottle(1);
    board.destroy();
    expect(log.closed).toBe(1);
    expect(log.stopped).toBe(3);
    const nodes = log.nodes;
    board.unlock();
    board.play("thud");
    expect(log.contexts).toBe(1);
    expect(log.nodes).toBe(nodes);
  });

  it("is a no-op when WebAudio is unsupported", () => {
    vi.stubGlobal("AudioContext", undefined);
    const board = createSoundboard();
    board.unlock();
    board.play("beep");
    board.setThrottle(1);
    board.destroy();
    expect(log.nodes).toBe(0);
  });
});
