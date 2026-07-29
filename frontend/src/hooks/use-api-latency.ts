"use client";

import { useEffect, useState } from "react";

import { getLastLatency, onLatencySample } from "@/lib/api-client";

/**
 * Real API round-trip latency, sampled from traffic the app is already making.
 *
 * The telemetry bar used to time a dedicated `/tokens?page_size=1` request every
 * twenty seconds, which duplicated a query the dashboard already ran and put a
 * request on the wire whose only purpose was to be measured. Reading the client's
 * own timing means the number reflects a call that had to happen anyway.
 */
export function useApiLatency(): number | null {
  const [latency, setLatency] = useState<number | null>(() => getLastLatency());

  useEffect(() => onLatencySample(setLatency), []);

  return latency;
}
