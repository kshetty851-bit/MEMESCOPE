"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/panel";
import { api } from "@/lib/api-client";

/**
 * Request a reset link.
 *
 * The confirmation is deliberately the same whether or not the address has an
 * account, and it says so. A form that distinguishes them is an
 * account-existence oracle anybody can query, and being coy about that would
 * only make the page look broken to the person whose address really is unknown.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/auth/password-reset/request", { email });
    } catch {
      // Deliberately ignored. A delivery or lookup failure must not change what
      // the page says, or the difference would answer the question the response
      // refuses to.
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <div>
        <Label>Check your inbox</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">Link on its way</h1>
        <p className="mt-3 text-sm text-ink-faint">
          If <span className="text-ink">{email}</span> has an account, a reset link is
          in it now. The link works once and expires in an hour; asking for another
          immediately invalidates it.
        </p>
        <p className="mt-6 text-center text-sm text-ink-faint">
          <Link href="/login" className="text-plasma transition-colors hover:text-ink">
            Back to sign in
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div>
      <Label>Account recovery</Label>
      <h1 className="mt-2 text-title font-semibold text-ink">Forgot your password</h1>
      <p className="mt-2 text-sm text-ink-faint">
        We will send a single-use link that expires in an hour.
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
        <Button type="submit" variant="primary" size="lg" loading={submitting}>
          Send reset link
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-ink-faint">
        Remembered it?{" "}
        <Link href="/login" className="text-plasma transition-colors hover:text-ink">
          Sign in
        </Link>
      </p>
    </div>
  );
}
