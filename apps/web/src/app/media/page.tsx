'use client';

import { ChangeEvent, FormEvent, useCallback, useContext, useEffect, useState } from 'react';
import Link from 'next/link';
import { Check, ChevronRight, Clock3, FileJson, Film, Loader2, Plus, Upload, X } from 'lucide-react';
import ProtectedRoute from '../components/ProtectedRoute';
import { UserContext } from '@/context/UserContext';
import { ImportedMediaSummary, importMedia, listImportedMedia, MediaImportRequest, TranscriptChunk } from './api';

type TranscriptFile = { model?: string; language?: string; timebase?: string; audio_seconds?: number; chunks: TranscriptChunk[] };

const formatDuration = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};

const episodeLabel = (media: ImportedMediaSummary) =>
  media.season === null || media.episode === null ? 'Episode' : `S${String(media.season).padStart(2, '0')} E${String(media.episode).padStart(2, '0')}`;

function validateTranscript(value: unknown): TranscriptFile {
  if (!value || typeof value !== 'object') throw new Error('The selected file is not valid JSON.');
  const transcript = value as Record<string, unknown>;
  if (!Array.isArray(transcript.chunks) || transcript.chunks.length === 0) throw new Error('The transcript must contain at least one chunk.');
  transcript.chunks.forEach((chunk, index) => {
    const item = chunk as Record<string, unknown>;
    if (!item || !Array.isArray(item.timestamp) || item.timestamp.length !== 2 || item.timestamp.some((time) => typeof time !== 'number') || typeof item.text !== 'string' || !item.text.trim()) {
      throw new Error(`Chunk ${index + 1} must have two timestamps and non-empty text.`);
    }
  });
  return transcript as TranscriptFile;
}

function MediaPageContent() {
  const { language } = useContext(UserContext);
  const languageCode = language?.code || 'es';
  const [media, setMedia] = useState<ImportedMediaSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showImport, setShowImport] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try { setMedia(await listImportedMedia(languageCode)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load imported media'); }
    finally { setLoading(false); }
  }, [languageCode]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="min-h-full bg-slate-50">
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-5 pt-8">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div><p className="mb-1 text-sm font-semibold uppercase tracking-widest text-indigo-600">Learn before you watch</p><h1 className="text-3xl font-bold tracking-tight text-slate-950">Series & Media</h1><p className="mt-2 max-w-xl text-slate-500">Turn your own episode transcripts into focused vocabulary practice.</p></div>
            <button onClick={() => setShowImport(true)} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 font-semibold text-white shadow-sm hover:bg-indigo-700"><Plus size={18}/> Import episode</button>
          </div>
          <div className="h-8" />
        </div>
      </div>

      <main className="mx-auto max-w-6xl px-5 py-8">
        {error && <div className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {loading ? <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin text-indigo-600"/></div> : media.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600"><FileJson size={28}/></div><h2 className="text-xl font-bold text-slate-900">Bring your first episode</h2><p className="mx-auto mt-2 max-w-md text-slate-500">Import a transcription JSON file and prepare the words you need before pressing play.</p><button onClick={() => setShowImport(true)} className="mt-6 rounded-lg bg-slate-900 px-4 py-2.5 font-semibold text-white">Choose transcript</button></div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{media.map((item) => (
            <Link key={item.id} href={`/media/${encodeURIComponent(item.id)}`} aria-label={`Open vocabulary for ${item.title}`} className="group rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"><article className="flex min-h-72 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition group-hover:-translate-y-0.5 group-hover:border-indigo-200 group-hover:shadow-lg">
              <div className="flex h-28 items-end bg-gradient-to-br from-indigo-700 via-violet-700 to-slate-900 p-5 text-white"><div><p className="text-xs font-bold uppercase tracking-widest text-indigo-200">{episodeLabel(item)}</p><h2 className="mt-1 line-clamp-1 text-xl font-bold">{item.series}</h2></div></div>
              <div className="flex flex-1 flex-col p-5"><h3 className="font-semibold text-slate-900">{item.title}</h3><div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500"><span className="flex items-center gap-1"><Clock3 size={14}/>{formatDuration(item.duration)}</span><span className="uppercase">{item.language}</span><span>{new Date(item.importedAt).toLocaleDateString()}</span></div>{item.transcriptionModel && <p className="mt-3 truncate text-xs text-slate-400" title={item.transcriptionModel}>{item.transcriptionModel}</p>}<div className="mt-auto flex justify-end border-t border-slate-100 pt-4 text-indigo-600 transition group-hover:translate-x-1"><ChevronRight size={19}/></div></div>
            </article></Link>
          ))}</div>
        )}
      </main>

      {showImport && <ImportDialog language={languageCode} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); refresh(); }}/>} 
    </div>
  );
}

function ImportDialog({ language, onClose, onImported }: { language: string; onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<TranscriptFile | null>(null); const [fileName, setFileName] = useState(''); const [series, setSeries] = useState(''); const [title, setTitle] = useState(''); const [season, setSeason] = useState(''); const [episode, setEpisode] = useState(''); const [error, setError] = useState(''); const [submitting, setSubmitting] = useState(false);
  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => { const chosen = event.target.files?.[0]; if (!chosen) return; setError(''); try { const parsed = validateTranscript(JSON.parse(await chosen.text())); setFile(parsed); setFileName(chosen.name); } catch (err) { setFile(null); setFileName(''); setError(err instanceof Error ? err.message : 'Unable to read this file'); } };
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!file) return setError('Choose a transcript JSON file first.'); if (!series.trim() || !title.trim() || season === '' || episode === '') return setError('Series, title, season, and episode are required.'); setSubmitting(true); setError(''); const request: MediaImportRequest = { series: series.trim(), title: title.trim(), season: Number(season), episode: Number(episode), media_type: 'series', language: file.language || language, model: file.model || null, timebase: file.timebase || null, audio_seconds: file.audio_seconds ?? null, chunks: file.chunks }; try { await importMedia(request); onImported(); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to import media'); } finally { setSubmitting(false); } };
  return <div className="fixed inset-0 z-[55] flex items-center justify-center overflow-y-auto bg-slate-950/60 p-4" onClick={!submitting ? onClose : undefined}><form onSubmit={submit} className="my-auto w-full max-w-xl rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}><div className="flex items-center justify-between border-b p-5"><div><h2 className="text-xl font-bold">Import an episode</h2><p className="text-sm text-slate-500">Add the episode details to your transcript.</p></div><button type="button" disabled={submitting} onClick={onClose} aria-label="Close" className="p-2 text-slate-400"><X/></button></div><div className="space-y-5 p-5">{error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}<label className={`flex cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed p-4 ${file ? 'border-emerald-300 bg-emerald-50' : 'border-slate-300 hover:border-indigo-400'}`}><input type="file" accept="application/json,.json" onChange={chooseFile} className="sr-only"/><span className={`rounded-lg p-2 ${file ? 'bg-emerald-100 text-emerald-700' : 'bg-indigo-50 text-indigo-600'}`}>{file ? <Check/> : <Upload/>}</span><span><strong className="block text-sm">{fileName || 'Choose transcription JSON'}</strong><span className="text-xs text-slate-500">{file ? `${file.chunks.length.toLocaleString()} chunks ready` : 'Your file is parsed locally before upload'}</span></span></label><div className="grid gap-4 sm:grid-cols-2"><Field label="Series name" value={series} setValue={setSeries} placeholder="Ozark"/><Field label="Episode title" value={title} setValue={setTitle} placeholder="Sugarwood"/><Field label="Season" value={season} setValue={setSeason} type="number" placeholder="1"/><Field label="Episode" value={episode} setValue={setEpisode} type="number" placeholder="1"/></div><div className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500"><Film size={16} className="mt-0.5 shrink-0"/> Importing a long episode may take a few minutes. Keep this window open while vocabulary is processed.</div></div><div className="flex justify-end gap-3 border-t p-5"><button type="button" disabled={submitting} onClick={onClose} className="rounded-lg px-4 py-2 font-semibold text-slate-600">Cancel</button><button disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 font-semibold text-white disabled:opacity-60">{submitting && <Loader2 size={16} className="animate-spin"/>}{submitting ? 'Processing episode…' : 'Import episode'}</button></div></form></div>;
}

function Field({ label, value, setValue, placeholder, type = 'text' }: { label: string; value: string; setValue: (value: string) => void; placeholder: string; type?: string }) { return <label className="text-sm font-semibold text-slate-700">{label}<input required min={type === 'number' ? 0 : undefined} type={type} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 font-normal outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"/></label>; }

export default function MediaPage() { return <ProtectedRoute><MediaPageContent/></ProtectedRoute>; }
