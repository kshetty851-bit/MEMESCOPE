import fs from "node:fs";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSpaceAudio,
  FADE_IN_SECONDS,
  FADE_OUT_SECONDS,
  MAX_VOLUME,
  SOUNDTRACK_URL,
} from "./space-audio";

/**
 * jsdom has an HTMLMediaElement but no playback, so the element is replaced
 * with a stand-in that records what the player asked of it. That is the whole
 * contract: what gets fetched, when it plays, how loud, and when it stops.
 */
class FakeAudio {
  static last: FakeAudio;
  src = "";
  currentTime = 0;
  loop = false;
  preload = "auto";
  paused = true;
  playResult: Promise<void> = Promise.resolve();
  private _volume = 1;
  private listeners: Record<string, Set<() => void>> = {};
  addEventListener(type: string, fn: () => void) {
    (this.listeners[type] ??= new Set()).add(fn);
  }
  removeEventListener(type: string, fn: () => void) {
    this.listeners[type]?.delete(fn);
  }
  /** Something outside the player — a media key, a phone call. */
  fire(type: "play" | "pause") {
    this.paused = type === "pause";
    this.listeners[type]?.forEach((fn) => fn());
  }

  constructor() {
    FakeAudio.last = this;
  }
  get volume() {
    return this._volume;
  }
  set volume(v: number) {
    // The real element throws outside [0, 1]; so does this one.
    if (v < 0 || v > 1) throw new RangeError(`volume ${v}`);
    this._volume = v;
  }
  play() {
    this.paused = false;
    return this.playResult;
  }
  pause() {
    this.paused = true;
  }
  load() {}
  removeAttribute(name: string) {
    if (name === "src") this.src = "";
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("Audio", FakeAudio);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the soundtrack", () => {
  it("is served from the media route, not from this repository", () => {
    expect(SOUNDTRACK_URL).toMatch(/\/media\/leokarlo-catwoman-instrumental\.mp3$/);
    // The repo is public: a commercial recording committed to it would be
    // downloadable from GitHub. None may live where the site bundles assets.
    const pub = path.join(process.cwd(), "public");
    const audio = fs.existsSync(pub)
      ? fs.readdirSync(pub, { recursive: true }).filter((f) =>
          /\.(mp3|m4a|ogg|wav|aac|opus)$/i.test(String(f)),
        )
      : [];
    expect(audio).toEqual([]);
  });

  it("downloads nothing until someone asks for it", () => {
    createSpaceAudio("/t.mp3");
    expect(FakeAudio.last.preload).toBe("none");
    expect(FakeAudio.last.paused).toBe(true);
  });

  it("loops, because it is background music and the track is under three minutes", () => {
    createSpaceAudio("/t.mp3");
    expect(FakeAudio.last.loop).toBe(true);
  });

  it("fades in to the ceiling and no further", async () => {
    const audio = createSpaceAudio("/t.mp3");
    await audio.start();
    expect(FakeAudio.last.paused).toBe(false);
    vi.advanceTimersByTime(FADE_IN_SECONDS * 1000 + 100);
    expect(FakeAudio.last.volume).toBeCloseTo(MAX_VOLUME, 5);
    expect(MAX_VOLUME).toBeLessThan(1);
  });

  it("goes quiet fast enough that off sounds like off", async () => {
    // Karthik once pressed off, kept hearing music, and reported it broken.
    expect(FADE_OUT_SECONDS).toBeLessThanOrEqual(0.5);

    const audio = createSpaceAudio("/t.mp3");
    await audio.start();
    vi.advanceTimersByTime(FADE_IN_SECONDS * 1000 + 100);

    audio.stop();
    vi.advanceTimersByTime(FADE_OUT_SECONDS * 1000 + 100);
    expect(FakeAudio.last.volume).toBe(0);
    expect(FakeAudio.last.paused).toBe(true);
  });

  it("does not let an old fade-out pause a track that was turned back on", async () => {
    const audio = createSpaceAudio("/t.mp3");
    await audio.start();
    audio.stop();
    // Back on before the fade-out finished.
    vi.advanceTimersByTime(100);
    await audio.start();
    vi.advanceTimersByTime(FADE_IN_SECONDS * 1000 + 100);
    expect(FakeAudio.last.paused).toBe(false);
    expect(FakeAudio.last.volume).toBeCloseTo(MAX_VOLUME, 5);
  });

  it("reports failure when the browser or the file refuses, so the button reads off", async () => {
    const audio = createSpaceAudio("/missing.mp3");
    FakeAudio.last.playResult = Promise.reject(new DOMException("no source", "NotSupportedError"));
    await expect(audio.start()).rejects.toThrow("no source");
    // And it is left silent, so a retry fades in rather than blaring.
    vi.advanceTimersByTime(FADE_IN_SECONDS * 1000 + 100);
    expect(FakeAudio.last.volume).toBe(0);
  });

  it("stays dead once disposed", async () => {
    const audio = createSpaceAudio("/t.mp3");
    audio.dispose();
    await audio.start();
    expect(FakeAudio.last.paused).toBe(true);
    expect(FakeAudio.last.src).toBe("");
  });
});

describe("the playback position the dance floor keeps time to", () => {
  it("is null until the track is playing, and while it is paused", async () => {
    const audio = createSpaceAudio("/t.mp3");
    expect(audio.position()).toBeNull();
    await audio.start();
    (FakeAudio.last as unknown as { currentTime: number }).currentTime = 12.5;
    expect(audio.position()).toBe(12.5);
    audio.stop();
    vi.advanceTimersByTime(FADE_OUT_SECONDS * 1000 + 100);
    expect(audio.position()).toBeNull();
  });

  it("is null once disposed, whatever the element says", async () => {
    const audio = createSpaceAudio("/t.mp3");
    await audio.start();
    audio.dispose();
    expect(audio.position()).toBeNull();
  });
});

describe("playback changed by something other than the button", () => {
  it("reports a pause it did not ask for", () => {
    const onPause = vi.fn();
    createSpaceAudio("/t.mp3", { onPause });
    FakeAudio.last.fire("pause");
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it("reports a resume it did not ask for", () => {
    const onPlay = vi.fn();
    createSpaceAudio("/t.mp3", { onPlay });
    FakeAudio.last.fire("play");
    expect(onPlay).toHaveBeenCalledTimes(1);
  });

  it("stops listening once disposed", () => {
    const onPause = vi.fn();
    const audio = createSpaceAudio("/t.mp3", { onPause });
    audio.dispose();
    onPause.mockClear();
    FakeAudio.last.fire("pause");
    expect(onPause).not.toHaveBeenCalled();
  });
});
