// Transcripts from files are always timed; only text sent from the reader isn't.
export type TimedChunk = { timestamp: [number, number]; text: string };

// What the file says it is a transcript of. Netling fills this in from the
// Netflix page the episode was armed on; other tools usually leave it out.
export interface TranscriptDetails {
  series: string | null;
  season: number | null;
  episode: number | null;
  title: string | null;
}

export interface ParsedTranscript {
  chunks: TimedChunk[];
  details: TranscriptDetails | null;
  language: string | null;
  model: string | null;
  timebase: string | null;
  audioSeconds: number | null;
  // Lines that were dropped (no text or no start time) or nudged to stop
  // overlapping their predecessor; shown so a bad file doesn't import silently.
  dropped: number;
  adjusted: number;
}

const str = (value: unknown) => (typeof value === 'string' && value.trim() ? value.trim() : null);
const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

// Reads every transcript shape we have met:
//   Netling (.whisper.json from the DeepInfra pipeline): { segments: [{ start, end, text }] }
//   transformers.js / the old in-browser Whisper export: { chunks: [{ timestamp: [a, b], text }] }
//   a bare array of either kind of line.
// The API only accepts the `chunks` form, ordered and non-overlapping, so this is
// where everything is brought into that shape. Whisper's segments regularly overlap
// by a few hundredths of a second, which the API rejects outright.
export function parseTranscript(value: unknown): ParsedTranscript {
  if (!value || typeof value !== 'object') throw new Error('This file is not a transcript.');
  const doc = value as Record<string, unknown>;
  const lines = Array.isArray(value) ? value : Array.isArray(doc.segments) ? doc.segments : Array.isArray(doc.chunks) ? doc.chunks : null;
  if (!lines) throw new Error('No transcript lines found. Expected a Netling .whisper.json with "segments", or a file with "chunks".');

  const raw: { start: number; end: number | null; text: string }[] = [];
  let dropped = 0;
  for (const line of lines) {
    const item = (line && typeof line === 'object' ? line : {}) as Record<string, unknown>;
    const [start, end] = Array.isArray(item.timestamp) ? [num(item.timestamp[0]), num(item.timestamp[1])] : [num(item.start), num(item.end)];
    const text = str(item.text);
    if (start === null || start < 0 || !text) { dropped += 1; continue; }
    raw.push({ start, end, text });
  }
  if (raw.length === 0) throw new Error('The transcript has no lines with both a start time and text.');

  raw.sort((a, b) => a.start - b.start);
  const chunks: TimedChunk[] = [];
  let previousEnd = 0;
  let adjusted = 0;
  for (const line of raw) {
    const start = Math.max(line.start, previousEnd);
    // transformers.js leaves the last chunk's end as null while it is still speaking.
    const end = Math.max(line.end ?? line.start + 2, start);
    if (start !== line.start || (line.end !== null && end !== line.end)) adjusted += 1;
    chunks.push({ timestamp: [start, end], text: line.text });
    previousEnd = end;
  }

  const media = doc.media && typeof doc.media === 'object' ? doc.media as Record<string, unknown> : null;
  const details = media && {
    series: str(media.series),
    season: num(media.season),
    episode: num(media.episode),
    title: str(media.title),
  };

  return {
    chunks,
    details: details && Object.values(details).some((value) => value !== null) ? details : null,
    language: str(doc.language),
    model: str(doc.model),
    timebase: str(doc.timebase),
    audioSeconds: num(doc.audio_seconds),
    dropped,
    adjusted,
  };
}
