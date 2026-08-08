import { cn } from "@/lib/utils";

export function SpaceBackground({
  active = false,
  className,
}: {
  active?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("alpha-space", active && "alpha-space--unlock", className)} aria-hidden>
      <div className="alpha-space__horizon" />
      <div className="alpha-space__nebula alpha-space__nebula--violet" />
      <div className="alpha-space__nebula alpha-space__nebula--cyan" />
      <div className="alpha-space__planet" />
      <div className="alpha-space__stars alpha-space__stars--far" />
      <div className="alpha-space__stars alpha-space__stars--near" />
      <div className="alpha-space__debris alpha-space__debris--one" />
      <div className="alpha-space__debris alpha-space__debris--two" />
      <div className="alpha-space__galaxy" />
      <div className="alpha-space__dust alpha-space__dust--back" />
      <div className="alpha-space__dust alpha-space__dust--front" />
      <div className="alpha-space__asteroid alpha-space__asteroid--one" />
      <div className="alpha-space__asteroid alpha-space__asteroid--two" />
      <div className="alpha-space__meteor alpha-space__meteor--one" />
      <div className="alpha-space__meteor alpha-space__meteor--two" />
      <div className="alpha-space__comet" />
      <div className="alpha-space__satellite" />
      <div className="alpha-space__probe" />
      <div className="alpha-space__ship" />
      <div className="alpha-space__scan" />
    </div>
  );
}
