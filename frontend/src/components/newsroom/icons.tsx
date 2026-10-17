/** One stroke family: 1.6px, round caps, drawn on a 20px grid. */
type P = { className?: string; title?: string };
const base = (title?: string) => ({ width: 20, height: 20, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor",
  strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": title ? undefined : true, role: title ? "img" : undefined });

export const IconPause = ({ className, title }: P) => <svg {...base(title)} className={className}>{title ? <title>{title}</title> : null}<path d="M7 4.5v11M13 4.5v11" /></svg>;
export const IconPlay = ({ className, title }: P) => <svg {...base(title)} className={className}>{title ? <title>{title}</title> : null}<path d="M6.5 4.5 15 10l-8.5 5.5z" /></svg>;
export const IconStar = ({ className, filled }: P & { filled?: boolean }) => <svg {...base()} className={className}><path d="m10 3 2.1 4.4 4.8.6-3.5 3.3.9 4.7L10 13.7 5.7 16l.9-4.7L3.1 8l4.8-.6z" fill={filled ? "currentColor" : "none"} /></svg>;
export const IconArrow = ({ className }: P) => <svg {...base()} className={className}><path d="M6 14 14 6M7.5 6H14v6.5" /></svg>;
export const IconSearch = ({ className }: P) => <svg {...base()} className={className}><circle cx="8.8" cy="8.8" r="5" /><path d="m12.6 12.6 4 4" /></svg>;
export const IconChevron = ({ className }: P) => <svg {...base()} className={className}><path d="m6 8 4 4 4-4" /></svg>;
export const IconShield = ({ className }: P) => <svg {...base()} className={className}><path d="M10 3 4.5 5v4.6c0 3.3 2.3 6 5.5 7.4 3.2-1.4 5.5-4.1 5.5-7.4V5z" /><path d="M10 7v3.6M10 13.2v.1" /></svg>;
export const IconRefresh = ({ className }: P) => <svg {...base()} className={className}><path d="M15.5 8.5a5.6 5.6 0 0 0-10.2-2M4.5 11.5a5.6 5.6 0 0 0 10.2 2" /><path d="M5 3.5v3h3M15 16.5v-3h-3" /></svg>;
