import { env } from "@/lib/env";

/**
 * THE SITE'S SOUNDTRACK: "MONTAGEM ALUCINANTE" (Rushex, DJ Orbital).
 *
 * This used to be a bell synthesiser — struck notes generated in the browser,
 * no audio file at all. Karthik replaced it with this track on 2026-09-17.
 *
 * WHERE THE FILE LIVES, AND WHERE IT MUST NOT
 *
 * Not in this repository. The repo is public, so a file committed here is a
 * file anyone can download from GitHub, and this is a commercial recording.
 * It is served by Caddy from a folder on the production host
 * (`~/MEMESCOPE/media`, gitignored) — see `docker/caddy/Caddyfile`. That also
 * puts it in front of the alpha gate, which matters: the button is on the
 * landing page, where nobody has unlocked anything yet, and the API would
 * answer 401.
 *
 * WHY A PLAIN <audio> ELEMENT
 *
 * Routing the element through Web Audio would give smooth fades everywhere,
 * but a cross-origin source inside a Web Audio graph plays as silence unless
 * the file carries CORS headers for every range request the browser makes.
 * The element on its own streams cross-origin with no configuration at all.
 * The cost is that iOS Safari ignores `volume`, so on an iPhone the track
 * starts and stops without a fade — it still starts and stops.
 *
 * WHY IT NEVER STARTS ON ITS OWN
 *
 * Every browser blocks audio until a real user gesture, and a site that plays
 * sound at someone unasked deserves the block. `start()` must be called from
 * a click handler, and it calls `play()` before anything else for that reason:
 * an `await` in front of it would move the call out of the gesture.
 */

export const SOUNDTRACK_URL = `${env.NEXT_PUBLIC_API_URL}/media/montagem-alucinante.mp3`;

/**
 * The track's tempo and where its first beat lands. MEASURED, not looked up.
 *
 * Folded the kick-drum onset envelope of the actual file at every tempo from
 * 124 to 138 BPM in 0.02 steps. 130.00 is the sharpest by a wide margin (7.01
 * against 5.39 at 130.02), and the first beat sits 26ms in. The phase holds in
 * each third of the track separately — 31, 26, 26ms — so there is no drift to
 * correct for, and 170.76s is 369.98 beats, so the loop lands on a beat too.
 *
 * The HQ dance floor steps to these. Change the song and these change with it,
 * or seventeen people dance confidently to the wrong tempo.
 */
export const TEMPO_BPM = 130;
export const BEAT_OFFSET_SECONDS = 0.026;

/**
 * The two fades are NOT the same length, and that asymmetry is the point.
 *
 * Both were once 2.5s. Fading in over 2.5s is fine; fading OUT over 2.5s is a
 * broken button — Karthik pressed off, kept hearing music, and reported it as
 * still playing. Off has to sound like off.
 */
export const FADE_IN_SECONDS = 1.2;
export const FADE_OUT_SECONDS = 0.3;

/**
 * Ceiling on the element's volume. This is a full-range club track rather than
 * the quiet bells it replaced, and it starts on a click — at full volume the
 * first bar would be a jolt, not a soundtrack.
 */
export const MAX_VOLUME = 0.5;

/** How often a fade takes a step. Degrades to ~1s in a background tab. */
const STEP_MS = 25;

export interface SpaceAudio {
  /** Must be called from a user gesture. Starts playing and fades in. */
  start(): Promise<void>;
  /** Fades out, then pauses. `start()` resumes from where it stopped. */
  stop(): void;
  /** Tears the whole thing down. After this the instance is dead. */
  dispose(): void;
  /**
   * Where playback is, in seconds, or `null` when nothing is playing.
   *
   * Read from the element itself rather than from a clock started on the
   * click: a track that stalls to buffer stops advancing, and anything keeping
   * time from a wall clock would carry on without it.
   */
  position(): number | null;
}

/** Whether this browser can play the soundtrack at all. */
export function audioSupported(win: Window & typeof globalThis = window): boolean {
  return typeof win.Audio === "function";
}

const clamp = (v: number) => Math.min(1, Math.max(0, v));

/**
 * Playback that started or stopped without the button.
 *
 * The element is the truth about whether sound is coming out, and plenty
 * besides the button can change it: a phone call, headphones unplugged, the
 * keyboard's media key, the OS's own media controls. Without these the button
 * went on reading "on" over a silent page — found when the HQ dance floor kept
 * dancing to a track that had stopped.
 */
export interface SpaceAudioEvents {
  onPlay?: () => void;
  onPause?: () => void;
}

export function createSpaceAudio(
  src: string = SOUNDTRACK_URL,
  events: SpaceAudioEvents = {},
): SpaceAudio {
  const el = new Audio();
  el.src = src;
  el.loop = true;
  if (events.onPlay) el.addEventListener("play", events.onPlay);
  if (events.onPause) el.addEventListener("pause", events.onPause);
  // Nothing is fetched until the first click. The track is 4MB and most
  // visitors never press the button.
  el.preload = "none";
  el.volume = 0;

  let disposed = false;
  let timer: number | null = null;

  function clearFade(): void {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  // An interval rather than requestAnimationFrame: rAF does not run at all in
  // a background tab, so a fade-out started there would never reach its
  // pause and the track would keep playing where nobody can see the button.
  //
  // Every fade cancels the one before it, callback included. That is what
  // stops a fade-out's pending pause from silencing a track that was turned
  // back on mid-fade — which would look exactly like the button failing.
  function fade(to: number, seconds: number, done?: () => void): void {
    clearFade();
    const from = el.volume;
    const steps = Math.max(1, Math.round((seconds * 1000) / STEP_MS));
    let step = 0;
    timer = window.setInterval(() => {
      step += 1;
      el.volume = clamp(from + ((to - from) * step) / steps);
      if (step >= steps) {
        clearFade();
        done?.();
      }
    }, STEP_MS);
  }

  return {
    async start() {
      if (disposed) return;
      const playing = el.play();
      // The fade starts now rather than once playback begins, deliberately: a
      // press of "off" while the track is still buffering then cancels this
      // fade, and the pause it schedules wins when playback finally starts.
      fade(MAX_VOLUME, FADE_IN_SECONDS);
      try {
        await playing;
      } catch (err) {
        // Refused by the browser, or the file would not load. Leave the
        // element silent and at rest, so the next attempt fades in from zero,
        // and let the caller report "off" — off is what can be heard.
        clearFade();
        el.volume = 0;
        throw err;
      }
    },
    stop() {
      if (disposed) return;
      fade(0, FADE_OUT_SECONDS, () => el.pause());
    },
    position() {
      return disposed || el.paused ? null : el.currentTime;
    },
    dispose() {
      disposed = true;
      clearFade();
      if (events.onPlay) el.removeEventListener("play", events.onPlay);
      if (events.onPause) el.removeEventListener("pause", events.onPause);
      el.pause();
      el.removeAttribute("src");
      el.load();
    },
  };
}
