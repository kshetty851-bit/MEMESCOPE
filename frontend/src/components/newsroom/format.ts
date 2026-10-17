/** Number and time formatting for the newspaper. Times are the reader's own. */
export function usd(v: number | null | undefined, digits?: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  for (const [div, unit] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]] as const) {
    if (a >= div && digits === undefined) return `$${(v / div).toFixed(2)}${unit}`;
  }
  if (a >= 1) return `$${v.toLocaleString("en-US", { maximumFractionDigits: digits ?? 2 })}`;
  return `$${v.toPrecision(3)}`;
}
export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const r = Number(v.toFixed(digits));
  return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r).toFixed(digits)}%`;
}
export function trend(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || Math.abs(v) < 0.05) return "flat";
  return v > 0 ? "up" : "down";
}
export function ago(iso: string, now: number): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
export function dayTime(iso: string): string {
  return new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function countdown(iso: string, now: number): string {
  let s = Math.max(0, Math.floor((Date.parse(iso) - now) / 1000));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  return d > 0 ? `${d}d ${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m` : `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
