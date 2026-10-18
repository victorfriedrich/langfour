'use client';

import { DragEvent, FormEvent, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, FileJson, Loader2, RefreshCw, Upload, X } from 'lucide-react';
import { UserContext } from '@/context/UserContext';
import { getLanguage } from '@/lib/languages';
import { ImportedMediaSummary, importMedia } from './api';
import { ParsedTranscript, parseTranscript } from './transcript';

const clock = (seconds: number) => {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, '0');
  return `${h ? `${h}:` : ''}${mm}:${String(s % 60).padStart(2, '0')}`;
};

const runtime = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
};

const code = (n: string) => String(Number(n)).padStart(2, '0');

interface Props {
  language: string;
  existing: ImportedMediaSummary[];
  onClose: () => void;
  onImported: () => void;
}

export default function ImportDialog({ language, existing, onClose, onImported }: Props) {
  const { fetchWithAuth } = useContext(UserContext);
  const inputRef = useRef<HTMLInputElement>(null);
  const seriesRef = useRef<HTMLInputElement>(null);
  const [transcript, setTranscript] = useState<ParsedTranscript | null>(null);
  const [fileName, setFileName] = useState('');
  const [fileError, setFileError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [series, setSeries] = useState('');
  const [season, setSeason] = useState('1');
  const [episode, setEpisode] = useState('1');
  const [title, setTitle] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !submitting) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, submitting]);

  const episodes = useMemo(() => existing.filter((item): item is ImportedMediaSummary & { series: string } => item.type === 'series' && !!item.series), [existing]);
  const seriesNames = useMemo(() => Array.from(new Set(episodes.map((item) => item.series))).sort(), [episodes]);
  const fileLanguage = transcript?.language ? getLanguage(transcript.language) : null;
  const targetLanguage = fileLanguage ?? getLanguage(language);
  const duplicate = episodes.find((item) =>
    item.series.trim().toLowerCase() === series.trim().toLowerCase() && item.season === Number(season) && item.episode === Number(episode));
  const ready = !!transcript && !!targetLanguage && !!series.trim() && season !== '' && episode !== '' && !duplicate && !submitting;

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setFileError(''); setSubmitError('');
    try {
      let json: unknown;
      try { json = JSON.parse(await file.text()); } catch { throw new Error(`${file.name} isn't valid JSON.`); }
      const parsed = parseTranscript(json);
      if (parsed.language && !getLanguage(parsed.language)) {
        throw new Error(`This transcript is in "${parsed.language}", which Langfour doesn't support yet.`);
      }
      setTranscript(parsed);
      setFileName(file.name);
      const details = parsed.details;
      if (details) {
        if (details.series) setSeries(details.series);
        if (details.season !== null) setSeason(String(details.season));
        if (details.episode !== null) setEpisode(String(details.episode));
        if (details.title) setTitle(details.title);
      }
      requestAnimationFrame(() => seriesRef.current?.focus());
    } catch (err) {
      setTranscript(null); setFileName('');
      setFileError(err instanceof Error ? err.message : 'Unable to read this file.');
    }
  };

  // Picking a series you've imported before continues where it left off.
  const chooseSeries = (value: string) => {
    setSeries(value);
    const previous = episodes
      .filter((item) => item.series.toLowerCase() === value.trim().toLowerCase() && item.season !== null && item.episode !== null)
      .sort((a, b) => (a.season! - b.season!) || (a.episode! - b.episode!));
    const last = previous[previous.length - 1];
    if (last) { setSeason(String(last.season)); setEpisode(String(last.episode! + 1)); }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault(); setDragging(false);
    if (!submitting) readFile(event.dataTransfer.files?.[0]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !transcript || !targetLanguage) return;
    setSubmitting(true); setSubmitError('');
    try {
      await importMedia(fetchWithAuth, {
        series: series.trim(),
        title: title.trim() || `Episode ${Number(episode)}`,
        season: Number(season),
        episode: Number(episode),
        media_type: 'series',
        language: targetLanguage.code,
        model: transcript.model,
        timebase: transcript.timebase,
        audio_seconds: transcript.audioSeconds,
        chunks: transcript.chunks,
      });
      onImported();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Unable to import this episode.');
      setSubmitting(false);
    }
  };

  const duration = transcript ? (transcript.audioSeconds ?? transcript.chunks[transcript.chunks.length - 1].timestamp[1]) : 0;
  const fixes = transcript ? transcript.adjusted + transcript.dropped : 0;
  // Whisper opens most episodes with "Música" / "Gracias." over the intro, and
  // hallucinates credits like "CC por Antarctica Films Argentina" that recur
  // through the file. Real dialogue (said once, a few words long) is what tells
  // you which episode this is.
  const preview = useMemo(() => {
    if (!transcript) return [];
    const counts = new Map<string, number>();
    transcript.chunks.forEach((chunk) => counts.set(chunk.text, (counts.get(chunk.text) ?? 0) + 1));
    const spoken = transcript.chunks.filter((chunk) => counts.get(chunk.text) === 1 && chunk.text.split(/\s+/).length >= 4);
    return (spoken.length >= 3 ? spoken : transcript.chunks).slice(0, 3);
  }, [transcript]);

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center overflow-y-auto bg-slate-950/60 p-4" onClick={!submitting ? onClose : undefined}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        onDragOver={(e) => { e.preventDefault(); if (!submitting) setDragging(true); }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }}
        onDrop={onDrop}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-title"
        className="my-auto w-full max-w-xl rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
          <div>
            <h2 id="import-title" className="text-xl font-bold text-slate-950">Import an episode</h2>
            <p className="mt-1 text-sm text-slate-500">Bring in a Netling recording&apos;s transcript and learn its words before you watch.</p>
          </div>
          <button type="button" disabled={submitting} onClick={onClose} aria-label="Close" className="-mr-2 -mt-1 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"><X size={20}/></button>
        </div>

        <input ref={inputRef} type="file" accept="application/json,.json" className="sr-only" tabIndex={-1}
          onChange={(e) => { readFile(e.target.files?.[0]); e.target.value = ''; }}/>

        <div className="space-y-5 px-6 pb-6">
          {!transcript ? (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className={`flex w-full flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${dragging ? 'border-indigo-500 bg-indigo-50' : fileError ? 'border-red-300 bg-red-50/40 hover:border-red-400' : 'border-slate-300 hover:border-indigo-400 hover:bg-slate-50'}`}
            >
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Upload size={22}/></span>
              <span className="font-semibold text-slate-900">{dragging ? 'Drop to read the transcript' : 'Drop a transcript here, or browse'}</span>
              <span className="mt-1 max-w-sm text-sm text-slate-500">
                Netling saves it next to the recording as <code className="rounded bg-slate-100 px-1 py-0.5 text-xs text-slate-600">Netflix-….whisper.json</code>. It&apos;s read in your browser first.
              </span>
            </button>
          ) : (
            <div className={`rounded-xl border bg-slate-50 ${dragging ? 'border-indigo-500' : 'border-slate-200'}`}>
              <div className="flex items-center gap-3 p-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white text-indigo-600 ring-1 ring-slate-200"><FileJson size={20}/></span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900" title={fileName}>{fileName}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {transcript.chunks.length.toLocaleString()} lines · {runtime(duration)}{fileLanguage ? ` · ${fileLanguage.name}` : ''}{transcript.model ? ` · ${transcript.model}` : ''}
                  </p>
                </div>
                <button type="button" disabled={submitting} onClick={() => inputRef.current?.click()} className="flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-semibold text-slate-600 hover:bg-white hover:text-slate-900 disabled:opacity-40"><RefreshCw size={14}/> Replace</button>
              </div>
              <ol className="space-y-1 border-t border-slate-200 px-4 py-3 text-sm" aria-label="First lines of the transcript">
                {preview.map((chunk, index) => (
                  <li key={index} className="flex gap-3">
                    <span className="w-10 shrink-0 text-right font-mono text-xs leading-5 text-slate-400">{clock(chunk.timestamp[0])}</span>
                    <span className="truncate text-slate-700">{chunk.text}</span>
                  </li>
                ))}
              </ol>
              {fixes > 0 && (
                <p className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
                  {[transcript.adjusted && `${transcript.adjusted} overlapping ${transcript.adjusted === 1 ? 'line' : 'lines'} trimmed`, transcript.dropped && `${transcript.dropped} empty ${transcript.dropped === 1 ? 'line' : 'lines'} skipped`].filter(Boolean).join(' · ')}
                </p>
              )}
            </div>
          )}

          {fileError && <p role="alert" className="-mt-2 flex items-start gap-2 text-sm text-red-700"><AlertCircle size={16} className="mt-0.5 shrink-0"/>{fileError}</p>}

          {transcript && (
            <fieldset disabled={submitting} className="space-y-4">
              <legend className="sr-only">Episode details</legend>
              <label className="block text-sm font-semibold text-slate-700">
                Series
                <input ref={seriesRef} required list="imported-series" value={series} onChange={(e) => chooseSeries(e.target.value)} placeholder="e.g. Ozark" className={inputClass}/>
                <datalist id="imported-series">{seriesNames.map((name) => <option key={name} value={name}/>)}</datalist>
              </label>
              <div className="grid grid-cols-[5.5rem_5.5rem_1fr] gap-3">
                <label className="block text-sm font-semibold text-slate-700">Season<input required type="number" min={0} inputMode="numeric" value={season} onChange={(e) => setSeason(e.target.value)} className={inputClass}/></label>
                <label className="block text-sm font-semibold text-slate-700">Episode<input required type="number" min={0} inputMode="numeric" value={episode} onChange={(e) => setEpisode(e.target.value)} className={inputClass}/></label>
                <label className="block text-sm font-semibold text-slate-700">Title <span className="font-normal text-slate-400">(optional)</span><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={episode !== '' ? `Episode ${Number(episode)}` : 'Episode title'} className={inputClass}/></label>
              </div>

              {duplicate && <Notice>You&apos;ve already imported {duplicate.series} S{code(season)} E{code(episode)}. Change the episode number to import another.</Notice>}
              {fileLanguage && fileLanguage.code !== getLanguage(language)?.code && (
                <Notice>This transcript is in {fileLanguage.name}. It will be listed under {fileLanguage.name}, not the language you&apos;re viewing now.</Notice>
              )}
            </fieldset>
          )}

          {submitError && <p role="alert" className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"><AlertCircle size={16} className="mt-0.5 shrink-0"/>{submitError}</p>}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-6 py-4">
          <p className="min-w-0 text-sm text-slate-500" aria-live="polite">
            {submitting
              ? `Finding the words in ${transcript?.chunks.length.toLocaleString()} lines. This can take a few minutes, so keep this open.`
              : transcript && series.trim() && season !== '' && episode !== '' ? <><span className="font-semibold text-slate-700">{series.trim()}</span> · S{code(season)} E{code(episode)}</> : null}
          </p>
          <div className="flex shrink-0 gap-2">
            {!submitting && <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 font-semibold text-slate-600 hover:bg-slate-100">Cancel</button>}
            <button disabled={!ready} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300">
              {submitting && <Loader2 size={16} className="animate-spin"/>}{submitting ? 'Importing…' : 'Import'}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

const inputClass = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base font-normal text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 sm:text-sm';

function Notice({ children }: { children: React.ReactNode }) {
  return <p className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800"><AlertCircle size={16} className="mt-0.5 shrink-0"/><span>{children}</span></p>;
}
