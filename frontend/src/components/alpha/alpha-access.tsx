"use client";

import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { ALPHA_ACCESS, BUILD } from "@/lib/env";
import { api } from "@/lib/api-client";
import type { AlphaSessionStatus } from "@/types/api";

export function AlphaAccess({ onUnlocking }: { onUnlocking: (active: boolean) => void }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void api
      .get<AlphaSessionStatus>("/alpha/session", { skipAuthRetry: true })
      .then((session) => {
        if (!cancelled && session.authenticated) router.replace(ALPHA_ACCESS.dashboardPath);
      })
      .catch(() => {
        // The launch screen is the safe fallback. Do not surface network errors
        // as password failures before the visitor submits anything.
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unlocking) return;

    setError(null);
    setUnlocking(true);
    onUnlocking(true);
    try {
      await api.post<AlphaSessionStatus>(
        "/alpha/unlock",
        { code },
        { skipAuthRetry: true },
      );
      window.sessionStorage.setItem(ALPHA_ACCESS.transitionKey, "true");
      window.setTimeout(() => router.push(ALPHA_ACCESS.dashboardPath), 1700);
    } catch {
      setError("Access code not recognised.");
      setUnlocking(false);
      onUnlocking(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="alpha-access rounded-panel border border-white/12 bg-abyss/55 p-5 shadow-2xl shadow-black/30 backdrop-blur-2xl"
    >
      <div className="text-center">
        <p className="text-label uppercase tracking-[0.24em] text-plasma">Alpha Access</p>
        <p className="mt-2 text-sm text-ink-faint">Private Alpha</p>
      </div>

      <label htmlFor="alpha-code" className="sr-only">
        Enter access code
      </label>
      <input
        id="alpha-code"
        value={code}
        onChange={(event) => {
          setCode(event.target.value);
          setError(null);
        }}
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder="Access code"
        disabled={unlocking}
        className="mt-5 h-12 w-full rounded-card border border-line bg-void/70 px-4 text-center font-mono text-lg tracking-[0.28em] text-ink outline-none transition-colors placeholder:text-ink-faint/50 focus:border-plasma disabled:opacity-70"
      />

      {error ? <p className="mt-2 text-center text-xs text-danger">{error}</p> : null}

      <button
        type="submit"
        disabled={unlocking}
        className="alpha-unlock mt-4 h-11 w-full rounded-card border border-plasma/30 bg-plasma/12 text-sm font-medium uppercase tracking-[0.18em] text-ink transition-all duration-300 hover:border-plasma/70 hover:bg-plasma/18 disabled:cursor-wait disabled:border-brand-secondary/60 disabled:bg-brand-secondary/15"
      >
        {unlocking ? "Unlocking" : "Unlock"}
      </button>

      <p className="mt-4 text-center text-xs text-ink-faint">
        Version {BUILD.version.replace(/^v/i, "")} Alpha
      </p>
    </form>
  );
}
