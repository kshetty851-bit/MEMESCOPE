"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled UI error", error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="max-w-md text-sm text-muted">
        The page failed to render. Retrying is usually enough; if it persists, quote
        reference <span className="font-mono text-xs">{error.digest ?? "n/a"}</span>.
      </p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
