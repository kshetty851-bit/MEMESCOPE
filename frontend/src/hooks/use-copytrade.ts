"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchCopyComparison } from "@/lib/copytrade";

export function useCopyComparison() {
  return useQuery({
    queryKey: ["copycontrol", "comparison"],
    queryFn: fetchCopyComparison,
    refetchInterval: 60_000,
  });
}
