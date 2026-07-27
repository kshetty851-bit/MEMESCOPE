"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";

const MIN_PASSWORD_LENGTH = 12;

export default function RegisterPage() {
  const router = useRouter();
  const { register, error, clearError } = useAuth();
  const [form, setForm] = useState({ email: "", password: "", displayName: "" });
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [field]: event.target.value }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();

    // Mirrors the server rule so the user gets feedback without a round trip.
    if (form.password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setFieldError(null);

    setSubmitting(true);
    try {
      await register({
        email: form.email,
        password: form.password,
        display_name: form.displayName || undefined,
      });
      router.replace("/dashboard");
    } catch {
      // Rendered from the store below.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
        <CardDescription>Start tracking Solana meme coins.</CardDescription>
      </CardHeader>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update("email")}
        />
        <Input
          label="Display name"
          type="text"
          autoComplete="nickname"
          value={form.displayName}
          onChange={update("displayName")}
          hint="Optional."
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          value={form.password}
          onChange={update("password")}
          error={fieldError ?? undefined}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters, with a letter and a digit.`}
        />

        {error && (
          <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <Button type="submit" loading={submitting}>
          Create account
        </Button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        Already registered?{" "}
        <Link href="/login" className="text-brand hover:underline">
          Sign in
        </Link>
      </p>
    </Card>
  );
}
