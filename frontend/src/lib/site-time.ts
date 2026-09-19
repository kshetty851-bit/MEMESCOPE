/**
 * EVERY CLOCK ON THE SITE READS DUBAI TIME, whatever the viewer's device says.
 *
 * The backend stores UTC and the site used to render in the reader's own zone,
 * so one trade read 14:30 on a phone in India and 13:00 in Dubai. Every one of
 * the site's ~50 formatters goes through `Date#toLocale*String`, so the zone is
 * set once, here, as the DEFAULT: a call that names its own `timeZone` keeps it
 * (the NSE tracker's exchange-day dates stay UTC on purpose).
 *
 * Imported for its side effect by `components/providers.tsx`, which runs on
 * the server render and in the browser alike, so the two agree.
 */

export const SITE_TIME_ZONE = "Asia/Dubai";
/** How the site names the zone in a label. Dubai keeps no daylight saving. */
export const SITE_TIME_LABEL = "Dubai";

type Format = (
  this: Date,
  locales?: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
) => string;

const PATCHED = Symbol.for("memescope.siteTimeZone");
const proto = Date.prototype as unknown as Record<string | symbol, unknown>;

if (!proto[PATCHED]) {
  for (const name of ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"] as const) {
    const original = Date.prototype[name] as Format;
    proto[name] = function (this: Date, locales?: Intl.LocalesArgument,
                            options?: Intl.DateTimeFormatOptions): string {
      return original.call(this, locales, { timeZone: SITE_TIME_ZONE, ...options });
    } satisfies Format;
  }
  proto[PATCHED] = true;
}
