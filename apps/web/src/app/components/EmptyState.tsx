import type { LucideIcon } from 'lucide-react';
import { BookOpen, FileText, Languages, Music, Newspaper, Tv } from 'lucide-react';
import type { ReactNode } from 'react';

// Concentric rings around one dark tile, with the kinds of things the app
// reads (songs, episodes, articles) drifting at the edges. Purely decorative.
const RINGS = [96, 168, 240, 312];
// Offsets in px from the centre tile, so the layout holds at any width.
const ORBIT: { icon: LucideIcon; x: number; y: number; size: 'sm' | 'md'; faded?: boolean }[] = [
  { icon: Newspaper, x: -31, y: -108, size: 'md' },
  { icon: Music, x: 54, y: -79, size: 'md' },
  { icon: Tv, x: -65, y: 22, size: 'md' },
  { icon: Languages, x: -100, y: -94, size: 'sm', faded: true },
  { icon: FileText, x: -92, y: 70, size: 'sm', faded: true },
  { icon: BookOpen, x: 108, y: 17, size: 'sm', faded: true },
];

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}

export default function EmptyState({ icon: Icon, title, children, actions }: EmptyStateProps) {
  return (
    <div className="relative overflow-hidden px-6 pb-12 pt-4 text-center">
      <div aria-hidden className="relative mx-auto h-60 w-full max-w-sm [mask-image:radial-gradient(circle_at_50%_55%,black_35%,transparent_75%)]">
        {RINGS.map((size) => (
          <span key={size} className="absolute left-1/2 top-[55%] -translate-x-1/2 -translate-y-1/2 rounded-full border border-gray-200" style={{ width: size, height: size }} />
        ))}
        {ORBIT.map(({ icon: OrbitIcon, x, y, size, faded }) => (
          <span key={`${x},${y}`} className={`absolute flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-xl bg-gray-50 text-gray-500 ring-1 ring-gray-200/70 ${size === 'md' ? 'h-11 w-11' : 'h-8 w-8'} ${faded ? 'opacity-60' : ''}`} style={{ left: `calc(50% + ${x}px)`, top: `calc(55% + ${y}px)` }}>
            <OrbitIcon size={size === 'md' ? 20 : 15} strokeWidth={1.75} />
          </span>
        ))}
        <span className="absolute left-1/2 top-[55%] flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl bg-gray-900 text-white shadow-lg shadow-gray-900/20">
          <Icon size={28} strokeWidth={2} />
        </span>
      </div>
      <h2 className="text-lg font-bold text-gray-900">{title}</h2>
      {children && <div className="mx-auto mt-2 max-w-md text-sm leading-6 text-gray-500">{children}</div>}
      {actions && <div className="mt-6 flex flex-wrap items-center justify-center gap-3">{actions}</div>}
    </div>
  );
}
