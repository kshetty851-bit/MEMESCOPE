import { api } from "@/lib/api-client";

import type { KarthikBook } from "./types";

/** One call, read-only. The book decides nothing; the arm behind it trades. */
export function fetchKarthikBook(): Promise<KarthikBook> {
  return api.get<KarthikBook>("/labs/graduation/karthik");
}
