import { cn } from "@/lib/utils";

/**
 * Loading states mirror the shape of what is arriving, never a spinner. A
 * spinner says "wait"; a skeleton says "here is what you are about to read",
 * which makes the same latency feel shorter.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton rounded-chip", className)} aria-hidden {...props} />;
}

export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className="h-3"
          style={{ width: index === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}

/** Placeholder shaped like a token card in the Live Scanner. */
export function SkeletonTokenCard() {
  return (
    <div className="rounded-panel border border-line bg-surface/60 p-5">
      <div className="flex items-center gap-3">
        <Skeleton className="size-10 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-3.5 w-32" />
          <Skeleton className="h-2.5 w-20" />
        </div>
        <Skeleton className="h-5 w-16" />
      </div>
      <div className="mt-5 grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="space-y-1.5">
            <Skeleton className="h-2 w-12" />
            <Skeleton className="h-3.5 w-16" />
          </div>
        ))}
      </div>
      <Skeleton className="mt-5 h-3 w-full" />
    </div>
  );
}
