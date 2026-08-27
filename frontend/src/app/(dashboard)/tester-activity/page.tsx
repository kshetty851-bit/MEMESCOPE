"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

type Session = {
  session_id: string;
  unlocked_at: string;
  last_seen_at: string;
  current_path: string;
  status: "active" | "idle" | "offline";
};
type Overview = { active_now: number; seen_today: number; sessions: Session[] };
const label = (value: string) => new Date(value).toLocaleString();
const duration = (startedAt: string) => {
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(startedAt).getTime()) / 60_000),
  );
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};

export default function TesterActivityPage() {
  const query = useQuery({
    queryKey: ["alpha-activity"],
    queryFn: () => api.get<Overview>("/alpha/activity"),
    refetchInterval: 15_000,
    retry: false,
  });
  if (query.isError)
    return (
      <main>
        <p className="text-label text-accent">Restricted</p>
        <h1 className="mt-2 text-2xl font-medium text-ink">
          Tester activity is available only to an account-level administrator.
        </h1>
      </main>
    );
  const data = query.data;
  return (
    <main>
      <p className="text-label text-accent">Private alpha</p>
      <h1 className="mt-2 text-3xl font-medium text-ink">Tester activity</h1>
      <p className="mt-2 text-sm text-ink-3">
        Anonymous session state only. Updates every 15 seconds.
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Active now</p>
          <p className="mt-2 text-3xl text-ink">{data?.active_now ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Today</p>
          <p className="mt-2 text-3xl text-ink">{data?.seen_today ?? "—"}</p>
        </div>
      </div>
      <div className="mt-6 overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-ink-3">
            <tr>
              <th className="p-3">Session</th>
              <th>First login</th>
              <th>Last active</th>
              <th>Session age</th>
              <th>Page</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {data?.sessions.map((row) => (
              <tr key={row.session_id} className="border-b border-line-subtle last:border-0">
                <td className="p-3 font-mono text-xs text-ink">
                  {row.session_id.slice(0, 8)}
                </td>
                <td>{label(row.unlocked_at)}</td>
                <td>{label(row.last_seen_at)}</td>
                <td>{duration(row.unlocked_at)}</td>
                <td>{row.current_path}</td>
                <td className="p-3">
                  <span
                    className={
                      row.status === "active"
                        ? "text-up"
                        : row.status === "idle"
                          ? "text-warn"
                          : "text-ink-3"
                    }
                  >
                    ● {row.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
