"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/panel";
import { useAuth } from "@/hooks/use-auth";

export default function LoginPage() {
  const router = useRouter();
  const { login, error, clearError, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const manualAuth = new URLSearchParams(window.location.search).get("auth") === "manual";
    if (!manualAuth && isAuthenticated) router.replace("/command");
  }, [isAuthenticated, router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();
    setSubmitting(true);
    try {
      await login({ email, password });
      router.replace("/command");
    } catch {
      // The store holds the message; the banner below renders it.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <Label>Secure access</Label>
      <h1 className="mt-2 text-title font-semibold text-ink">Enter the Command Center</h1>
      <p className="mt-2 text-sm text-ink-faint">
        Authenticate to reach live intelligence.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 flex flex-col gap-5" noValidate>
        <Input
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {error && (
          <p
            role="alert"
            className="rounded-card border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <Button type="submit" variant="primary" size="lg" loading={submitting}>
          Authenticate
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-ink-faint">
        No clearance?{" "}
        <Link href="/register" className="text-plasma transition-colors hover:text-ink">
          Request access
        </Link>
      </p>
    </div>
  );
}
