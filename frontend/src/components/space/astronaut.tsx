/**
 * A HUMAN ASTRONAUT, FLOATING (Karthik, 2026-09-27). Drawn, not a photo: a
 * white suit with a gold visor, backpack and a loose tether, tumbling slowly
 * across the sky on a CSS path (`.home-universe__spacewalker`).
 */
export function HumanAstronautArt() {
  return (
    <svg viewBox="0 0 140 170" width="100%" height="100%" aria-hidden focusable="false">
      <defs>
        <linearGradient id="ha-suit" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#c9d2e3" />
        </linearGradient>
        <linearGradient id="ha-visor" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffd98a" />
          <stop offset="0.45" stopColor="#e39b2d" />
          <stop offset="1" stopColor="#5b3a12" />
        </linearGradient>
      </defs>
      {/* tether, drifting off behind */}
      <path d="M40 104 C 10 120, 6 150, 24 168" fill="none" stroke="#9aa6bd" strokeWidth="2.5"
            strokeLinecap="round" strokeDasharray="1 5" />
      {/* backpack */}
      <rect x="30" y="58" width="80" height="62" rx="12" fill="#aab4c8" />
      {/* legs */}
      <rect x="44" y="112" width="22" height="42" rx="10" fill="url(#ha-suit)" transform="rotate(8 55 112)" />
      <rect x="74" y="112" width="22" height="42" rx="10" fill="url(#ha-suit)" transform="rotate(-10 85 112)" />
      <rect x="42" y="146" width="26" height="12" rx="5" fill="#8e98ad" transform="rotate(8 55 150)" />
      <rect x="74" y="146" width="26" height="12" rx="5" fill="#8e98ad" transform="rotate(-10 87 150)" />
      {/* body */}
      <rect x="38" y="62" width="64" height="62" rx="18" fill="url(#ha-suit)" />
      <rect x="54" y="80" width="32" height="20" rx="4" fill="#e8ecf4" stroke="#b7c0d2" />
      <circle cx="61" cy="90" r="2.5" fill="#e0564b" />
      <circle cx="70" cy="90" r="2.5" fill="#3aa7ff" />
      <circle cx="79" cy="90" r="2.5" fill="#57c26a" />
      {/* arms, one waving */}
      <rect x="14" y="70" width="30" height="18" rx="9" fill="url(#ha-suit)" transform="rotate(-28 30 78)" />
      <rect x="96" y="58" width="30" height="18" rx="9" fill="url(#ha-suit)" transform="rotate(-52 110 66)" />
      <circle cx="16" cy="88" r="8" fill="#8e98ad" />
      <circle cx="122" cy="40" r="8" fill="#8e98ad" />
      {/* helmet and visor */}
      <circle cx="70" cy="40" r="32" fill="url(#ha-suit)" stroke="#b7c0d2" strokeWidth="2" />
      <ellipse cx="72" cy="42" rx="22" ry="18" fill="url(#ha-visor)" />
      <ellipse cx="64" cy="35" rx="7" ry="4" fill="#fff5dd" opacity="0.75" transform="rotate(-25 64 35)" />
    </svg>
  );
}
