import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="font-mono text-sm text-brand">404</p>
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link href="/">
        <Button variant="secondary">Back home</Button>
      </Link>
    </main>
  );
}
