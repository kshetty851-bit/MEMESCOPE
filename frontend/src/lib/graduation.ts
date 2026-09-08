import { api } from "@/lib/api-client";

import type { GraduationCohort } from "@/types/graduation";

/** The graduation cohort. Fetches and formats; the accounting is server-side. */
export function fetchGraduations(): Promise<GraduationCohort> {
  return api.get<GraduationCohort>("/pumpfun/graduations");
}
