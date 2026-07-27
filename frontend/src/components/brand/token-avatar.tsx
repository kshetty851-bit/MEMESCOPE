import { cn } from "@/lib/utils";

/**
 * Token avatar.
 *
 * Most new mints have no logo, and the ones that do host it on IPFS behind
 * unpredictable latency. Rather than a grey circle or a broken image, every
 * token gets a deterministic sigil derived from its mint address: an orbital
 * ring plus three nodes whose angles and hue come from the address itself.
 *
 * Same mint always produces the same mark, so tokens become visually
 * recognisable in a scrolling feed — which is the actual job of an avatar.
 */

function hash(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

export function TokenAvatar({
  mint,
  size = 40,
  className,
}: {
  mint: string;
  size?: number;
  className?: string;
}) {
  const h = hash(mint);
  // Steer away from gold (85°) — that hue belongs to APEX alone.
  const hue = (h % 300) + 190;
  const tone = `oklch(0.75 0.15 ${hue % 360})`;
  const nodes = [0, 1, 2].map((index) => {
    const angle = ((h >> (index * 5)) % 360) * (Math.PI / 180);
    return {
      x: 16 + Math.cos(angle) * 9,
      y: 16 + Math.sin(angle) * 9,
      r: 1.6 + ((h >> (index * 3)) % 3) * 0.5,
    };
  });

  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={cn("shrink-0 rounded-full", className)}
      style={{ background: `color-mix(in oklch, ${tone} 12%, transparent)` }}
      aria-hidden
    >
      <circle
        cx="16"
        cy="16"
        r="12"
        fill="none"
        stroke={tone}
        strokeWidth="1"
        strokeDasharray="3 4"
        opacity="0.5"
      />
      <circle cx="16" cy="16" r="4.5" fill="none" stroke={tone} strokeWidth="1.2" />
      {nodes.map((node, index) => (
        <circle key={index} cx={node.x} cy={node.y} r={node.r} fill={tone} />
      ))}
    </svg>
  );
}
