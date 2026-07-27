import Link from "next/link";

import { AiCore } from "@/components/brand/ai-core";
import { Universe } from "@/components/brand/universe/universe";
import { Logo } from "@/components/brand/logo";
import { Label } from "@/components/ui/panel";

/**
 * Auth is a two-panel airlock: the instrument on the left, the credential form
 * on the right. On mobile the Core collapses away — a login screen on a phone
 * needs the keyboard, not the atmosphere.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-screen lg:grid-cols-2">
      <Universe minimal />

      {/* Left: the instrument */}
      <aside className="relative hidden flex-col justify-between border-r border-line/60 bg-abyss/40 p-10 backdrop-blur-xl lg:flex">
        <Link href="/">
          <Logo />
        </Link>

        <div className="flex flex-col items-center gap-10">
          <AiCore size={340} />
          <div className="max-w-sm text-center">
            <Label>AI Crypto Intelligence</Label>
            <p className="mt-3 text-balance text-heading text-ink">
              Seven AI specialists scanning Solana, continuously.
            </p>
          </div>
        </div>

        <p className="text-xs text-ink-faint">
          Intelligence, not advice. Always do your own research.
        </p>
      </aside>

      {/* Right: credentials */}
      <main className="flex flex-col items-center justify-center px-6 py-12">
        <Link href="/" className="mb-10 lg:hidden">
          <Logo />
        </Link>
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}
