'use client';

import { useCallback, useContext, useEffect, useState } from 'react';
import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';
import { ChevronRight, Clapperboard, FileText, Film, Music, Newspaper, Plus, Tv } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import ProtectedRoute from '../components/ProtectedRoute';
import { UserContext } from '@/context/UserContext';
import { ImportedMediaSummary, listImportedMedia } from './api';
import ImportDialog from './ImportDialog';

// The same two buttons as the Practice page.
const primary = 'inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700';
const secondary = 'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50';

const formatDuration = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
};

const timeToFinish = (media: ImportedMediaSummary) =>
  media.duration ? formatDuration(media.duration) : media.wordCount ? `${Math.max(1, Math.round(media.wordCount / 200))} min read` : null;

const hostOf = (url: string | null | undefined) => {
  try { return url ? new URL(url).hostname.replace(/^www\./, '') : null; } catch { return null; }
};

// What each row shows under the title: who or where it is from, then the
// episode number for series. The title itself is always the item's own.
const rowDetails = (media: ImportedMediaSummary): { icon: LucideIcon; kind: string; parts: (string | null | undefined)[] } => {
  switch (media.type) {
    case 'series':
      return {
        icon: Tv,
        kind: 'Episode',
        parts: [media.series, media.season === null || media.episode === null ? null : `S${String(media.season).padStart(2, '0')} E${String(media.episode).padStart(2, '0')}`],
      };
    case 'article':
      return { icon: Newspaper, kind: 'Article', parts: [media.site || hostOf(media.sourceUrl)] };
    case 'song':
      return { icon: Music, kind: 'Song', parts: [media.artist] };
    case 'movie':
      return { icon: Film, kind: 'Movie', parts: [] };
    default:
      return { icon: FileText, kind: 'Text', parts: [] };
  }
};

function MediaPageContent() {
  const { language, fetchWithAuth } = useContext(UserContext);
  const languageCode = language?.code || 'es';
  const [media, setMedia] = useState<ImportedMediaSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showImport, setShowImport] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try { setMedia(await listImportedMedia(fetchWithAuth, languageCode)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load imported media'); }
    finally { setLoading(false); }
  }, [fetchWithAuth, languageCode]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="min-h-screen bg-white">
      <div className="max-w-3xl px-4 py-10 sm:px-8">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Media</h1>
            <p className="mt-1 text-sm text-gray-500">Learn the words of an episode, article or song before you start.</p>
          </div>
          {media.length > 0 && <button onClick={() => setShowImport(true)} className={secondary}><Plus size={16}/>Import episode</button>}
        </header>

        {error && <p className="mb-6 text-sm text-red-600">{error}</p>}
        {loading ? (
          <div className="divide-y divide-gray-100 border-t border-gray-100" aria-label="Loading">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex items-center gap-4 py-4 pl-1">
                <span className="h-4 w-4 animate-pulse rounded bg-gray-100" />
                <span className="h-3 w-56 animate-pulse rounded bg-gray-100" />
              </div>
            ))}
          </div>
        ) : media.length === 0 ? (
          !error && <EmptyState icon={Clapperboard} title="Nothing in your library yet" actions={<>
            <Link href="/extension" className={secondary}>Get the extension</Link>
            <button onClick={() => setShowImport(true)} className={primary}><Plus size={16}/>Import episode</button>
          </>}>Import an episode transcript here, or add an article or song from the extension&apos;s reader with Add to Library.</EmptyState>
        ) : (
          <ul className="divide-y divide-gray-100 border-t border-gray-100">{media.map((item) => <MediaRow key={item.id} item={item}/>)}</ul>
        )}
      </div>

      {showImport && <ImportDialog language={languageCode} existing={media} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); refresh(); }}/>}
    </div>
  );
}

function MediaRow({ item }: { item: ImportedMediaSummary }) {
  const { icon: Icon, kind, parts } = rowDetails(item);
  const details = [...parts, timeToFinish(item)].filter(Boolean).join(' · ');
  return (
    <li>
      <Link href={`/media/${encodeURIComponent(item.id)}`} aria-label={`Open vocabulary for ${item.title}`} className="group flex items-center gap-4 py-4 pl-1 pr-2 hover:bg-gray-50 focus:outline-none focus-visible:bg-gray-50">
        <Icon size={18} className="shrink-0 text-gray-400" aria-label={kind}/>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-gray-900">{item.title}</p>
          {details && <p className="mt-0.5 truncate text-sm text-gray-500">{details}</p>}
        </div>
        <span className="hidden shrink-0 text-sm tabular-nums text-gray-400 sm:block">{new Date(item.importedAt).toLocaleDateString()}</span>
        <ChevronRight size={16} className="shrink-0 text-gray-300 group-hover:text-gray-500"/>
      </Link>
    </li>
  );
}

export default function MediaPage() { return <ProtectedRoute><MediaPageContent/></ProtectedRoute>; }
