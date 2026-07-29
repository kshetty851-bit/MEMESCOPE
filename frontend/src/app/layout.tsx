import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { MODE_BOOT_SCRIPT } from "@/hooks/use-observatory-mode";
import { env } from "@/lib/env";
import "@/styles/globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  // The wordmark is MEMESCOPE, always. The env var carries a legacy display
  // name and must not be allowed to leak into brand surfaces.
  title: {
    default: "MEMESCOPE — AI Crypto Intelligence",
    template: "%s · MEMESCOPE",
  },
  description:
    "The Intelligence Division continuously scans Solana, analyses every launch and discovers opportunities before the market reacts.",
  robots:
    env.NEXT_PUBLIC_ENVIRONMENT === "production" ? "index,follow" : "noindex,nofollow",
};

export const viewport: Viewport = {
  // Matches --color-void, so the browser chrome blends into the canvas.
  themeColor: "#0d0f17",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-mode="observatory" suppressHydrationWarning>
      <head>
        {/* Applies the stored display mode before first paint, so a user who
            chose Command never sees a flash of Observatory atmosphere. */}
        <script dangerouslySetInnerHTML={{ __html: MODE_BOOT_SCRIPT }} />
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
