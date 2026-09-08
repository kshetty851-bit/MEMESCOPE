import { api } from "@/lib/api-client";

import type { GraduationCohort, GraduationPaper } from "@/types/graduation";

/** The graduation cohort. Fetches and formats; the accounting is server-side. */
export function fetchGraduations(): Promise<GraduationCohort> {
  return api.get<GraduationCohort>("/pumpfun/graduations");
}

/** The simulated $100 book. Accounting is server-side so one implementation
 *  owns it and the page cannot disagree with a query run by hand. */
export function fetchGraduationPaper(): Promise<GraduationPaper> {
  return api.get<GraduationPaper>("/pumpfun/graduations/paper");
}
