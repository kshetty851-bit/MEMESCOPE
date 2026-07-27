import "@testing-library/jest-dom/vitest";

// `env.ts` validates these at import time; supply defaults for the test run.
process.env.NEXT_PUBLIC_API_URL ??= "http://localhost:8000";
process.env.NEXT_PUBLIC_APP_NAME ??= "MemeScope AI";
process.env.NEXT_PUBLIC_ENVIRONMENT ??= "local";
