import type { MetadataRoute } from "next";

/** Home-screen app (Karthik, 2026-10-17): installs full-screen from Safari's "Add to Home Screen". */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "MEMESCOPE",
    short_name: "MEMESCOPE",
    description: "pump.fun graduation lab and real wallet",
    start_url: "/real-wallet",
    display: "standalone",
    background_color: "#111318",
    theme_color: "#111318",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
