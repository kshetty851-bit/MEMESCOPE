import { api } from "@/lib/api-client";

import type {
  DataOut,
  FetchIn,
  ImportBatch,
  ImportIn,
  MetaOut,
  QualityReport,
  RunDetail,
  RunIn,
  RunKind,
  RunOut,
  VersionIn,
  VersionOut,
} from "./types";

/**
 * FOREX LAB CLIENT. Research and paper only: every POST either stores candles,
 * replays stored candles through a strategy, or saves a config. None of them
 * can reach a broker — there is no broker in this codebase to reach.
 */
const BASE = "/labs/forex";

export function fetchMeta(): Promise<MetaOut> {
  return api.get<MetaOut>(`${BASE}/meta`);
}

export function fetchData(): Promise<DataOut> {
  return api.get<DataOut>(`${BASE}/data`);
}

export function fetchQuality(
  symbol: string,
  timeframe: string,
  start?: string,
  end?: string,
): Promise<QualityReport> {
  const q = new URLSearchParams({ symbol, timeframe });
  if (start) q.set("start", start);
  if (end) q.set("end", end);
  return api.get<QualityReport>(`${BASE}/data/quality?${q.toString()}`);
}

export function importCsv(body: ImportIn): Promise<ImportBatch> {
  return api.post<ImportBatch>(`${BASE}/data/import`, body);
}

export function startFetch(body: FetchIn): Promise<RunOut> {
  return api.post<RunOut>(`${BASE}/data/fetch`, body);
}

export function fetchRuns(kind?: RunKind, limit = 50): Promise<{ runs: RunOut[] }> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (kind) q.set("kind", kind);
  return api.get<{ runs: RunOut[] }>(`${BASE}/runs?${q.toString()}`);
}

export function fetchRun(id: number): Promise<RunDetail> {
  return api.get<RunDetail>(`${BASE}/runs/${id}`);
}

export function createRun(body: RunIn): Promise<RunOut> {
  return api.post<RunOut>(`${BASE}/runs`, body);
}

export function fetchVersions(): Promise<{ versions: VersionOut[] }> {
  return api.get<{ versions: VersionOut[] }>(`${BASE}/versions`);
}

export function createVersion(body: VersionIn): Promise<VersionOut> {
  return api.post<VersionOut>(`${BASE}/versions`, body);
}
