'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { ReviewProvider } from '../hooks/useReviewProvider';
import type { RemnoteConnection } from '../hooks/useRemnoteConnection';

const DAY_MS = 86_400_000;

function timeAgo(iso: string, now: number) {
  const minutes = Math.round((now - Date.parse(iso)) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

interface SchedulerLabelProps {
  provider: ReviewProvider;
  remnote: RemnoteConnection | null;
  onDisconnect: () => Promise<void>;
}

/** Who schedules, in one quiet line: the only place the page names RemNote
 *  once it is connected. Amber when RemNote has not synced for two days.
 *  The connection's details and Disconnect sit behind it. */
export default function SchedulerLabel({ provider, remnote, onDisconnect }: SchedulerLabelProps) {
  const [now] = useState(() => Date.now());
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const lastSync = remnote?.token_last_used_at ?? null;
  const inRemnote = provider === 'remnote';
  const stale = inRemnote && (!lastSync || now - Date.parse(lastSync) > 2 * DAY_MS);
  const label = inRemnote ? `Scheduled in RemNote${lastSync ? ` · synced ${timeAgo(lastSync, now)}` : ''}` : 'Scheduled by Langfour';
  const dot = <i className={`h-1.5 w-1.5 rounded-full ${stale ? 'bg-amber-500' : 'bg-emerald-500'}`} />;

  if (!inRemnote || !remnote?.connected) {
    return <span className="inline-flex items-center gap-2 text-xs text-gray-500">{dot}{label}</span>;
  }

  const disconnect = async () => {
    if (!window.confirm('Disconnect RemNote? Reviews move back to Langfour. Your RemNote cards stay where they are.')) return;
    setBusy(true);
    setError(null);
    try {
      await onDisconnect();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="-mr-2 inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-800"
        aria-expanded={open}
      >
        {dot}
        {label}
        <ChevronDown size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-gray-200 bg-white p-4 text-sm shadow-lg">
          <p className="text-gray-700">
            <b className="font-semibold tabular-nums text-gray-900">{remnote.linked_words.toLocaleString()}</b> words sync with RemNote.
            New words you save are added there automatically.
          </p>
          <button
            onClick={disconnect}
            disabled={busy}
            className="mt-3 text-gray-500 underline-offset-2 hover:text-gray-800 hover:underline disabled:opacity-50"
          >
            Disconnect RemNote
          </button>
          {error && <p className="mt-2 text-red-600">{error}</p>}
        </div>
      )}
    </div>
  );
}
