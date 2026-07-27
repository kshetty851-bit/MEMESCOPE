"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";
import type { User } from "@/types/api";

export default function DashboardPage() {
  const { user } = useAuth();

  // Proves the authenticated request path end to end: bearer token, refresh on
  // 401, error envelope. Feature queries follow this exact shape.
  const { data: profile, isPending } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get<User>("/users/me"),
    initialData: user ?? undefined,
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted">
          Foundation is live. Discovery features are not wired up yet.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>Your session details.</CardDescription>
          </CardHeader>
          <dl className="flex flex-col gap-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Email</dt>
              <dd className="truncate font-mono text-xs">{profile?.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Role</dt>
              <dd>{profile?.role}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Last sign-in</dt>
              <dd>{isPending ? "…" : formatDate(profile?.last_login_at ?? null)}</dd>
            </div>
          </dl>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Scanner</CardTitle>
            <CardDescription>Solana pool discovery.</CardDescription>
          </CardHeader>
          <p className="text-sm text-muted">Not implemented — scheduled for a later day.</p>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>AI scoring</CardTitle>
            <CardDescription>Risk and momentum signals.</CardDescription>
          </CardHeader>
          <p className="text-sm text-muted">Not implemented — scheduled for a later day.</p>
        </Card>
      </div>
    </div>
  );
}
