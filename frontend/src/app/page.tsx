import Link from "next/link";

import { Button } from "@/components/ui/button";
import { env } from "@/lib/env";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-8 px-6 text-center">
      <div className="flex flex-col gap-4">
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-brand">
          Solana · Day 1 Foundation
        </p>
        <h1 className="text-balance text-4xl font-semibold sm:text-5xl">
          {env.NEXT_PUBLIC_APP_NAME}
        </h1>
        <p className="text-balance text-muted">
          The platform scaffold is live: authentication, API, database, cache, and
          observability. Discovery features land on top of this foundation.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <Link href="/register">
          <Button>Create an account</Button>
        </Link>
        <Link href="/login">
          <Button variant="secondary">Sign in</Button>
        </Link>
      </div>
    </main>
  );
}
