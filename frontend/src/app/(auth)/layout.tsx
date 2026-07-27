import Link from "next/link";

import { env } from "@/lib/env";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 py-12">
      <Link href="/" className="text-sm font-semibold tracking-tight text-brand">
        {env.NEXT_PUBLIC_APP_NAME}
      </Link>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
