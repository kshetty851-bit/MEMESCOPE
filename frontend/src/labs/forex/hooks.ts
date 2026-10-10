"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createRun,
  createVersion,
  fetchData,
  fetchMeta,
  fetchQuality,
  fetchRun,
  fetchRuns,
  fetchVersions,
  importCsv,
  startFetch,
} from "./api";
import type { FetchIn, ImportIn, RunDetail, RunIn, RunKind, VersionIn } from "./types";

/** A run is polled while the worker may still be changing it, and not after. */
export const POLL_MS = 2_000;

export function isActive(status: string | undefined): boolean {
  return status === "queued" || status === "running";
}

/** Strategies, bounds and defaults change on a deploy only. */
export function useForexMeta() {
  return useQuery({
    queryKey: ["forex", "meta"],
    queryFn: fetchMeta,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useForexData() {
  return useQuery({ queryKey: ["forex", "data"], queryFn: fetchData });
}

export function useQuality(symbol: string | null, timeframe: string | null) {
  return useQuery({
    queryKey: ["forex", "quality", symbol, timeframe],
    queryFn: () => fetchQuality(symbol!, timeframe!),
    enabled: Boolean(symbol && timeframe),
  });
}

export function useImportCsv() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ImportIn) => importCsv(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["forex", "data"] });
      void client.invalidateQueries({ queryKey: ["forex", "quality"] });
    },
  });
}

export function useStartFetch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: FetchIn) => startFetch(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["forex", "runs"] }),
  });
}

export function useRuns(kind?: RunKind) {
  return useQuery({
    queryKey: ["forex", "runs", kind ?? "all"],
    queryFn: () => fetchRuns(kind),
  });
}

/**
 * One run, polled every two seconds while it is queued or running and left
 * alone once it is done or failed. The poll decision reads the data the query
 * itself holds, so it stops the moment the answer says it should — there is no
 * second flag to keep in step.
 */
export function useRun(id: number | null) {
  const client = useQueryClient();
  return useQuery<RunDetail>({
    queryKey: ["forex", "run", id],
    queryFn: async () => {
      const detail = await fetchRun(id!);
      // The runs list and the data panel are stale the moment a run finishes.
      if (!isActive(detail.run.status)) {
        void client.invalidateQueries({ queryKey: ["forex", "runs"] });
        if (detail.run.kind === "fetch") {
          void client.invalidateQueries({ queryKey: ["forex", "data"] });
          void client.invalidateQueries({ queryKey: ["forex", "quality"] });
        }
      }
      return detail;
    },
    enabled: id !== null,
    refetchInterval: (query) => (isActive(query.state.data?.run.status) ? POLL_MS : false),
    refetchOnWindowFocus: false,
  });
}

export function useCreateRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RunIn) => createRun(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["forex", "runs"] }),
  });
}

export function useVersions() {
  return useQuery({ queryKey: ["forex", "versions"], queryFn: fetchVersions });
}

export function useCreateVersion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: VersionIn) => createVersion(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["forex", "versions"] }),
  });
}
