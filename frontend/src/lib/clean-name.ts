/**
 * Coin names are chosen by whoever launched the coin, and pump.fun is full of
 * obscene and hateful ones. Public pages show a stand-in instead (2026-10-20,
 * after one turned up in the homepage's live checkpoint).
 */
const ANYWHERE = /fuck|shit|cunt|pussy|vagina|penis|porn|nigg|faggot|retard|rapist|slut|whore|bitch|asshole|boob|dildo|blowjob|handjob|hitler|nazi|cocksuck|jizz|semen|anus/;
const WHOLE = new Set(["ass", "cum", "sex", "tits", "tit", "cock", "dick", "fag", "rape", "anal", "kkk", "milf", "nude", "nudes", "horny"]);

export function isRude(name: string | null | undefined): boolean {
  if (!name) return false;
  const flat = name.toLowerCase().replace(/[^a-z]/g, "");
  if (ANYWHERE.test(flat)) return true;
  return name.toLowerCase().split(/[^a-z]+/).some((w) => WHOLE.has(w));
}

export function cleanName(name: string | null | undefined): string | null | undefined {
  return isRude(name) ? "(name hidden)" : name;
}
