import { z } from "zod";

/**
 * Public runtime configuration.
 *
 * Next.js inlines `NEXT_PUBLIC_*` at build time, so these must be referenced by
 * their full literal name — destructuring `process.env` would not be replaced.
 * Parsing here means a missing variable fails the build, not a user's session.
 */
const publicEnvSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://localhost:8000"),
  NEXT_PUBLIC_APP_NAME: z.string().default("LetzMooN AI"),
  NEXT_PUBLIC_ENVIRONMENT: z.enum(["local", "staging", "production"]).default("local"),
  // Development only. Read through `AUTH_BYPASS`, never directly.
  NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH: z.enum(["true", "false"]).default("false"),

  // --- Alpha ---------------------------------------------------------------
  // The commit the running bundle was built from. `deploy.sh` passes the short
  // SHA as a build arg; "unknown" means someone built outside that path, which
  // is worth being able to see rather than hiding behind a plausible default.
  NEXT_PUBLIC_BUILD_SHA: z.string().default("unknown"),
  NEXT_PUBLIC_VERSION: z.string().default("0.8.0-rc1"),
  NEXT_PUBLIC_ALPHA: z.enum(["true", "false"]).default("false"),
  // Blank hides the feedback control entirely. A button that goes nowhere is
  // worse than no button: it collects nothing and spends the tester's goodwill
  // the first time they press it.
  NEXT_PUBLIC_FEEDBACK_URL: z.string().default(""),
  // A real endpoint to POST reports to. Takes precedence over the URL above:
  // an in-product form that never leaves the page is a far lower barrier than
  // sending a tester to a third-party tab mid-thought.
  NEXT_PUBLIC_FEEDBACK_ENDPOINT: z.string().default(""),

  // --- Analytics -----------------------------------------------------------
  // Optional. With no key nothing loads and no request is made, so development
  // and CI stay free of both a network call and a secret.
  NEXT_PUBLIC_POSTHOG_KEY: z.string().default(""),
  NEXT_PUBLIC_POSTHOG_HOST: z.string().default("https://eu.i.posthog.com"),
});

const parsed = publicEnvSchema.safeParse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_ENVIRONMENT: process.env.NEXT_PUBLIC_ENVIRONMENT,
  NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH: process.env.NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH,
  NEXT_PUBLIC_BUILD_SHA: process.env.NEXT_PUBLIC_BUILD_SHA,
  NEXT_PUBLIC_VERSION: process.env.NEXT_PUBLIC_VERSION,
  NEXT_PUBLIC_ALPHA: process.env.NEXT_PUBLIC_ALPHA,
  NEXT_PUBLIC_FEEDBACK_URL: process.env.NEXT_PUBLIC_FEEDBACK_URL,
  NEXT_PUBLIC_FEEDBACK_ENDPOINT: process.env.NEXT_PUBLIC_FEEDBACK_ENDPOINT,
  NEXT_PUBLIC_POSTHOG_KEY: process.env.NEXT_PUBLIC_POSTHOG_KEY,
  NEXT_PUBLIC_POSTHOG_HOST: process.env.NEXT_PUBLIC_POSTHOG_HOST,
});

if (!parsed.success) {
  throw new Error(
    `Invalid public environment configuration:\n${JSON.stringify(
      parsed.error.flatten().fieldErrors,
      null,
      2,
    )}`,
  );
}

export const env = parsed.data;

export const API_V1 = `${env.NEXT_PUBLIC_API_URL}/api/v1`;

/**
 * Whether to skip the sign-in flow entirely and treat the visitor as a
 * developer.
 *
 * The flag is anded with the environment here, once, so no call site can enable
 * it in a production build by forgetting the check. The backend applies exactly
 * the same rule and refuses to boot if the flag is set in production, so the
 * two halves cannot drift into a state where the UI hides a login the API still
 * requires.
 *
 * While active: no session bootstrap, no refresh request, no redirect to
 * `/login`. The auth pages and every line of auth code remain in place - this
 * only changes whether they are reached.
 */
export const AUTH_BYPASS =
  env.NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH === "true" &&
  env.NEXT_PUBLIC_ENVIRONMENT !== "production";

/**
 * Alpha build identity, for the banner and the version badge.
 *
 * Kept together so the surfaces that display build provenance all read one
 * object rather than each reaching for a different environment variable and
 * disagreeing about what is running.
 */
export const BUILD = {
  version: env.NEXT_PUBLIC_VERSION,
  sha: env.NEXT_PUBLIC_BUILD_SHA,
  environment: env.NEXT_PUBLIC_ENVIRONMENT,
  isAlpha: env.NEXT_PUBLIC_ALPHA === "true",
  feedbackUrl: env.NEXT_PUBLIC_FEEDBACK_URL,
} as const;

/**
 * Whether product analytics should load.
 *
 * A key is the switch. Nothing is imported or requested without one, so the
 * default posture is "no third-party script on the page".
 */
export const ANALYTICS_ENABLED = env.NEXT_PUBLIC_POSTHOG_KEY !== "";
