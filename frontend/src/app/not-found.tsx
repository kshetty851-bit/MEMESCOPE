import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Universe } from "@/components/brand/universe/universe";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/panel";

export default function NotFound() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <Universe minimal />

      <Logo className="absolute left-6 top-6" size={20} />

      <div className="ambient flex size-16 items-center justify-center rounded-full border border-scout/30 bg-scout/10 text-scout animate-[breathe_6s_ease-in-out_infinite]">
        <AgentSigil agent="scout" size={30} />
      </div>

      <div className="max-w-md space-y-3">
        <Label>Error 404</Label>
        <h1 className="text-title font-semibold text-ink">
          SCOUT swept this sector. Nothing here.
        </h1>
        <p className="text-sm text-ink-faint">
          The page you asked for does not exist. The division is still watching everything
          that does.
        </p>
      </div>

      <div className="flex gap-3">
        <Link href="/command">
          <Button variant="primary">Return to Command Center</Button>
        </Link>
        <Link href="/feed">
          <Button variant="outline">Open Market Observatory</Button>
        </Link>
      </div>
    </main>
  );
}
