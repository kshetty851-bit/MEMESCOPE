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
  NEXT_PUBLIC_APP_NAME: z.string().default("MemeScope AI"),
  NEXT_PUBLIC_ENVIRONMENT: z
    .enum(["local", "staging", "production"])
    .default("local"),
});

const parsed = publicEnvSchema.safeParse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_ENVIRONMENT: process.env.NEXT_PUBLIC_ENVIRONMENT,
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
