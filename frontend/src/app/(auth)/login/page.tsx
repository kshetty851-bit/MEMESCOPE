"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";

export default function LoginPage() {
  const router = useRouter();
  const { login, error, clearError, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();
    setSubmitting(true);
    try {
      await login({ email, password });
      router.replace("/dashboard");
    } catch {
      // The store holds the message; the banner below renders it.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Access your MemeScope dashboard.</CardDescription>
      </CardHeader>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
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
          <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <Button type="submit" loading={submitting}>
          Sign in
        </Button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        No account?{" "}
        <Link href="/register" className="text-brand hover:underline">
          Create one
        </Link>
      </p>
    </Card>
  );
}
