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
      <div className="alpha-space__nebula alpha-space__nebula--violet" />
      <div className="alpha-space__nebula alpha-space__nebula--cyan" />
      <div className="alpha-space__planet" />
      <div className="alpha-space__stars alpha-space__stars--far" />
      <div className="alpha-space__stars alpha-space__stars--near" />
      <div className="alpha-space__scan" />
    </div>
  );
}
