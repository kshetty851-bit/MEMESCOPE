import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";

import { Providers } from "@/components/providers";
import { MODE_BOOT_SCRIPT } from "@/hooks/use-display-mode";
import { RAIL_BOOT_SCRIPT } from "@/hooks/use-nav-rail";
import { SPACE_BOOT_SCRIPT } from "@/hooks/use-space";
import { env } from "@/lib/env";
import "@/styles/globals.css";
import "@/styles/memescope.css";
import "@/styles/universe.css";
import "@/styles/home-universe.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
/**
 * The display face: the wordmark, the hero, section headings and agent names.
 *
 * One extra family, not three. Space Grotesk is geometric enough to read as an
 * instrument and odd enough not to read as a bank — and it ships the 300 and
 * 700 the wordmark needs to split MEME from SCOPE by weight alone.
 *
 * Two axes only. Loading the full range would be four more files for weights
 * nothing uses, on a page whose first paint is the product's only first
 * impression.
 */
const display = Space_Grotesk({
  variable: "--font-display-face",
  subsets: ["latin"],
  weight: ["300", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  // The wordmark is MEMESCOPE, always. The env var carries a legacy display
  // name and must not be allowed to leak into brand surfaces.
  title: {
    default: "MEMESCOPE — Pump.fun Intelligence",
    template: "%s · MEMESCOPE",
  },
  description:
    "MEMESCOPE tracks every Pump.fun launch, scores it deterministically, and publishes the result — winners and losers alike.",
  robots:
    env.NEXT_PUBLIC_ENVIRONMENT === "production" ? "index,follow" : "noindex,nofollow",
};

export const viewport: Viewport = {
  // Matches --color-canvas, so the browser chrome blends into the shell.
  themeColor: "#111318",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    /* The font variables belong on <html>, not <body>.

       Every font token in `globals.css` lives in `@theme`, which emits to
       `:root` — and `:root` *is* <html>. With the variable classes on <body>,
       `--font-sans: var(--font-geist-sans)` resolved against a variable that
       did not exist at that level, the whole declaration was invalid, and the
       site fell back to the browser's default sans. It had never actually
       rendered in Geist. Moving them up makes every token resolve where it is
       declared. */
    <html
      lang="en"
      data-mode="full"
      data-rail="expanded"
      data-space="full"
      className={`${geistSans.variable} ${geistMono.variable} ${display.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Both run before first paint so neither the ambient mode nor the
            rail width changes shape after hydration. */}
        <script dangerouslySetInnerHTML={{ __html: MODE_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: RAIL_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: SPACE_BOOT_SCRIPT }} />
      </head>
      <body className="antialiased">
        {/* The first stop for a keyboard user: the rail is nine links deep and
            skipping it should not require nine presses on every navigation. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-overlay focus:px-3 focus:py-2 focus:text-sm focus:text-ink"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
