import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import { SITE_TIME_ZONE } from "./site-time";

/** Merge conditional class names, with later Tailwind utilities winning. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: SITE_TIME_ZONE,
  }).format(new Date(iso));
}
