"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { apiFetch } from "@/lib/api-client";

/** Web Push wants the VAPID key as raw bytes, not base64url text. */
function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

type State = "checking" | "unsupported" | "install-first" | "off" | "on" | "busy" | "blocked";

/**
 * PHONE ALERTS (Karthik, 2026-10-17): real-wallet trades as push notifications
 * on this device. On iPhone they work only from the home-screen app (iOS 16.4+),
 * which is why the panel says "add to home screen" first when it is opened in Safari.
 */
export function PhoneAlerts() {
  const [state, setState] = useState<State>("checking");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      const standalone = typeof window !== "undefined" && window.matchMedia?.("(display-mode: standalone)").matches;
      setState(/iphone|ipad/i.test(navigator.userAgent) && !standalone ? "install-first" : "unsupported");
      return;
    }
    if (Notification.permission === "denied") { setState("blocked"); return; }
    navigator.serviceWorker.register("/sw.js")
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setState(sub ? "on" : "off"))
      .catch(() => setState("unsupported"));
  }, []);

  async function turnOn() {
    setState("busy"); setNote(null);
    try {
      if ((await Notification.requestPermission()) !== "granted") { setState("blocked"); return; }
      const reg = await navigator.serviceWorker.register("/sw.js");
      const { key } = await apiFetch<{ key: string }>("/push/public-key");
      const sub = (await reg.pushManager.getSubscription())
        ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
      await apiFetch("/push/subscribe", { method: "POST", body: sub.toJSON() });
      await apiFetch("/push/test", { method: "POST" });
      setState("on"); setNote("A test alert is on its way.");
    } catch (error) {
      setState("off"); setNote(error instanceof Error ? error.message : "Could not turn alerts on.");
    }
  }

  const text: Record<State, string> = {
    checking: "Checking this device…",
    unsupported: "This browser cannot receive alerts.",
    "install-first": "On iPhone: tap Share → Add to Home Screen, open MEMESCOPE from the home screen, then come back here.",
    off: "Get a notification on this device when the real wallet buys or sells.",
    busy: "Turning on…",
    on: "Alerts are on for this device.",
    blocked: "Notifications are blocked for MEMESCOPE. Allow them in the phone's Settings → Notifications.",
  };
  return (
    <Panel density="comfortable">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-8">
        <div className="min-w-0 max-w-md">
          <h3 className="text-sm font-medium text-ink">Phone alerts</h3>
          <p className="mt-1 text-xs leading-relaxed text-ink-2">{text[state]}</p>
          {note ? <p className="mt-1.5 text-xs leading-relaxed text-ink-3">{note}</p> : null}
        </div>
        {state === "off" || state === "on" ? (
          <Button variant={state === "off" ? "primary" : "outline"} onClick={turnOn}>
            {state === "off" ? "Turn on alerts" : "Send a test"}
          </Button>
        ) : null}
      </div>
    </Panel>
  );
}
