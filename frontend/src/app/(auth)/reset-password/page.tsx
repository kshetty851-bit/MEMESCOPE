"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/panel";
import { ApiError, api } from "@/lib/api-client";

/**
 * Spend a reset link.
 *
 * The token arrives in the query string, is posted once, and is never stored
 * anywhere by this page. Completing a reset ends every existing session on the
 * server, so the page sends the reader to sign in rather than pretending they
 * are already authenticated.
 */
function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const tooShort = password.length > 0 && password.length < 12;
  const mismatch = confirm.length > 0 && confirm !== password;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Those passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/auth/password-reset/complete", {
        token,
        new_password: password,
      });
      setDone(true);
      setTimeout(() => router.replace("/login"), 2500);
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "That reset link is no longer valid. Request a new one.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div>
        <Label>Account recovery</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">Link incomplete</h1>
        <p className="mt-3 text-sm text-ink-faint">
          This page needs the token from your reset email. Open the link from the
          email itself, or request a new one.
        </p>
        <p className="mt-6 text-center text-sm text-ink-faint">
          <Link
            href="/forgot-password"
            className="text-plasma transition-colors hover:text-ink"
          >
            Request a new link
          </Link>
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div>
        <Label>Account recovery</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">Password updated</h1>
        <p className="mt-3 text-sm text-ink-faint">
          Every existing session was signed out, including any you did not start.
          Taking you to sign in&hellip;
        </p>
      </div>
    );
  }

  return (
    <div>
      <Label>Account recovery</Label>
      <h1 className="mt-2 text-title font-semibold text-ink">Choose a new password</h1>
      <p className="mt-2 text-sm text-ink-faint">
        At least 12 characters. Saving it signs out every existing session.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 flex flex-col gap-5" noValidate>
        <Input
          label="New password"
          type="password"
          name="new-password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <Input
          label="Confirm new password"
          type="password"
          name="confirm-password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />

        {(error || tooShort || mismatch) && (
          <p
            role="alert"
            className="rounded-card border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm text-danger"
          >
            {error ??
              (tooShort
                ? "Use at least 12 characters."
                : "Those passwords do not match.")}
          </p>
        )}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          loading={submitting}
          disabled={password.length < 12 || password !== confirm}
        >
          Set new password
        </Button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  // `useSearchParams` needs a Suspense boundary in the app router.
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
