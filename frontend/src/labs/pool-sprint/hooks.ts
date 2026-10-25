"use client";

import { useQuery } from "@tanstack/react-query";

import { api, getAccessToken } from "@/lib/api-client";
import { API_V1 } from "@/lib/env";

import type { SprintBook, SprintTrades } from "./types";

const PATH = "/labs/graduation/pool-sprint";

export function usePoolSprintBook() {
  return useQuery({
    queryKey: ["pool-sprint", "book"],
    queryFn: () => api.get<SprintBook>(PATH),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function usePoolSprintTrades(day: string | null, status: string, offset: number) {
  const params = new URLSearchParams({ status, offset: String(offset), limit: "100" });
  if (day) params.set("day", day);
  return useQuery({
    queryKey: ["pool-sprint", "trades", day, status, offset],
    queryFn: () => api.get<SprintTrades>(`${PATH}/trades?${params}`),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export async function downloadPoolSprintCsv() {
  // Use the normal client first so an expired session receives its usual refresh.
  await api.get<SprintBook>(PATH);
  const token = getAccessToken();
  const response = await fetch(`${API_V1}${PATH}/trades.csv`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error("Could not download paper trades");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "pool-sprint-trades.csv";
  link.click();
  URL.revokeObjectURL(url);
}
