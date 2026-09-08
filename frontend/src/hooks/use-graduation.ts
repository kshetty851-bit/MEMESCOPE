"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchGraduationCycles,
  fetchGraduationPaper,
  fetchGraduations,
} from "@/lib/graduation";

export function useGraduations() {
  return useQuery({
    queryKey: ["pumpfun", "graduations"],
    queryFn: fetchGraduations,
    refetchInterval: 60_000,
  });
}

export function useGraduationPaper() {
  return useQuery({
    queryKey: ["pumpfun", "graduations", "paper"],
    queryFn: fetchGraduationPaper,
    refetchInterval: 60_000,
  });
}

export function useGraduationCycles() {
  return useQuery({
    queryKey: ["pumpfun", "graduations", "cycles"],
    queryFn: fetchGraduationCycles,
    refetchInterval: 60_000,
  });
}
