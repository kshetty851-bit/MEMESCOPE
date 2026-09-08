"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchGraduations } from "@/lib/graduation";

export function useGraduations() {
  return useQuery({
    queryKey: ["pumpfun", "graduations"],
    queryFn: fetchGraduations,
    refetchInterval: 60_000,
  });
}
