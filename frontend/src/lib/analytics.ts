/**
 * Product analytics integration point.
 *
 * PostHog is loaded lazily and only when a key is configured, so a deployment
 * without one ships no third-party script, makes no request, and needs no
 * secret. That also keeps development and the test suite clean by default.
 *
 * `posthog-js` is intentionally NOT a dependency yet. This module is the seam:
 * `npm i posthog-js`, uncomment the import, and the surrounding wiring — the
 * key, the host, the opt-out posture, the identify call — is already decided.
 * Adding 60 KB of vendor script to every page load before a single alpha tester
 * has asked for a funnel would be paying now for a decision not yet made.
 *
 * Nothing here sends personal data. The alpha has no user-level analytics
 * requirement, and the moment it does, that is a privacy decision to take
 * deliberately rather than inherit from a default.
 */

import { ANALYTICS_ENABLED, env } from "@/lib/env";

export interface AnalyticsEvent {
  name: string;
  properties?: Record<string, string | number | boolean>;
}

let initialised = false;

/** Start analytics if configured. Safe to call more than once. */
export async function initAnalytics(): Promise<boolean> {
  if (!ANALYTICS_ENABLED || initialised || typeof window === "undefined") {
    return false;
  }
  initialised = true;

  // --- Enable by installing posthog-js and uncommenting -------------------
  // const posthog = (await import("posthog-js")).default;
  // posthog.init(env.NEXT_PUBLIC_POSTHOG_KEY, {
  //   api_host: env.NEXT_PUBLIC_POSTHOG_HOST,
  //   // The App Router does not emit page views on client navigation, so they
  //   // are captured explicitly in `track` instead of relying on autocapture.
  //   capture_pageview: false,
  //   // Off during an alpha: session recordings of a handful of known testers
  //   // are a lot of personal data for very little signal.
  //   disable_session_recording: true,
  //   persistence: "localStorage",
  // });

  return true;
}

/** Record an event. A no-op until analytics is both configured and installed. */
export function track(event: AnalyticsEvent): void {
  if (!ANALYTICS_ENABLED || !initialised) return;

  // const posthog = (window as { posthog?: { capture: (n: string, p?: object) => void } }).posthog;
  // posthog?.capture(event.name, event.properties);
  void event;
}

/** The configured host, exposed so a CSP connect-src can be derived from it. */
export const ANALYTICS_HOST = env.NEXT_PUBLIC_POSTHOG_HOST;
