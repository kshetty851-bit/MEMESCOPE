"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { api } from "@/lib/api-client";

const HEARTBEAT_MS = 25_000;

/** First-party route heartbeat; it sends no query string, device, or input data. */
export function ActivityHeartbeat() {
  const pathname = usePathname();

  useEffect(() => {
    const beat = () => {
      if (document.visibilityState === "visible") {
        void api.post("/alpha/activity", { path: pathname }, { skipAuthRetry: true });
      }
    };
    beat();
    const timer = window.setInterval(beat, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", beat);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", beat);
    };
  }, [pathname]);

  return null;
}
