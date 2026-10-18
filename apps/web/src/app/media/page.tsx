'use client';

import { useCallback, useContext, useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, Clock3, FileJson, Loader2, Plus } from 'lucide-react';
import ProtectedRoute from '../components/ProtectedRoute';
import { UserContext } from '@/context/UserContext';
import { ImportedMediaSummary, listImportedMedia } from './api';
import ImportDialog from './ImportDialog';

const formatDuration = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
};

// What each kind of item shows on its card: the small label above the name,
// the name itself, and how long it takes to get through.
const cardHeading = (media: ImportedMediaSummary) => {
  switch (media.type) {
    case 'series':
      return {
        label: media.season === null || media.episode === null ? 'Episode' : `S${String(media.season).padStart(2, '0')} E${String(media.episode).padStart(2, '0')}`,
        name: media.series || media.title,
        tone: 'from-indigo-700 via-violet-700 to-slate-900',
      };
    case 'article':
      return { label: 'Article', name: media.site || hostOf(media.sourceUrl) || media.title, tone: 'from-sky-700 via-cyan-800 to-slate-900' };
    case 'song':
      return { label: 'Song', name: media.artist || media.title, tone: 'from-rose-600 via-fuchsia-800 to-slate-900' };
    default:
      return { label: media.type === 'movie' ? 'Movie' : 'Text', name: media.title, tone: 'from-slate-600 via-slate-700 to-slate-900' };
  }
};

const timeToFinish = (media: ImportedMediaSummary) =>
  media.duration ? formatDuration(media.duration) : media.wordCount ? `${Math.max(1, Math.round(media.wordCount / 200))} min read` : null;

const hostOf = (url: string | null | undefined) => {
  try { return url ? new URL(url).hostname.replace(/^www\./, '') : null; } catch { return null; }
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
    <div className="min-h-full bg-slate-50">
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-5 pt-8">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div><p className="mb-1 text-sm font-semibold uppercase tracking-widest text-indigo-600">Learn before you start</p><h1 className="text-3xl font-bold tracking-tight text-slate-950">Series & Media</h1><p className="mt-2 max-w-xl text-slate-500">Episodes, articles and songs: learn their words before you start.</p></div>
            <button onClick={() => setShowImport(true)} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 font-semibold text-white shadow-sm hover:bg-indigo-700"><Plus size={18}/> Import episode</button>
          </div>
          <div className="h-8" />
        </div>
      </div>

      <main className="mx-auto max-w-6xl px-5 py-8">
        {error && <div className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {loading ? <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin text-indigo-600"/></div> : media.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600"><FileJson size={28}/></div><h2 className="text-xl font-bold text-slate-900">Nothing in your library yet</h2><p className="mx-auto mt-2 max-w-md text-slate-500">Import an episode transcript here, or send an article or song from the Langfour reader with Add to Library.</p><button onClick={() => setShowImport(true)} className="mt-6 rounded-lg bg-slate-900 px-4 py-2.5 font-semibold text-white">Import episode</button></div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{media.map((item) => <MediaCard key={item.id} item={item}/>)}</div>
        )}
      </main>

      {showImport && <ImportDialog language={languageCode} existing={media} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); refresh(); }}/>} 
    </div>
  );
}

function MediaCard({ item }: { item: ImportedMediaSummary }) {
  const heading = cardHeading(item);
  const time = timeToFinish(item);
  return (
    <Link href={`/media/${encodeURIComponent(item.id)}`} aria-label={`Open vocabulary for ${item.title}`} className="group rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2">
      <article className="flex min-h-72 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition group-hover:-translate-y-0.5 group-hover:border-indigo-200 group-hover:shadow-lg">
        <div className={`flex h-28 items-end bg-gradient-to-br ${heading.tone} p-5 text-white`}>
          <div className="min-w-0"><p className="text-xs font-bold uppercase tracking-widest text-white/70">{heading.label}</p><h2 className="mt-1 line-clamp-1 text-xl font-bold">{heading.name}</h2></div>
        </div>
        <div className="flex flex-1 flex-col p-5">
          <h3 className="line-clamp-2 font-semibold text-slate-900">{item.title}</h3>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500">{time && <span className="flex items-center gap-1"><Clock3 size={14}/>{time}</span>}<span className="uppercase">{item.language}</span><span>{new Date(item.importedAt).toLocaleDateString()}</span></div>
          {item.transcriptionModel && <p className="mt-3 truncate text-xs text-slate-400" title={item.transcriptionModel}>{item.transcriptionModel}</p>}
          <div className="mt-auto flex justify-end border-t border-slate-100 pt-4 text-indigo-600 transition group-hover:translate-x-1"><ChevronRight size={19}/></div>
        </div>
      </article>
    </Link>
  );
}

export default function MediaPage() { return <ProtectedRoute><MediaPageContent/></ProtectedRoute>; }
