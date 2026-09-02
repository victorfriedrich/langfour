export interface TranscriptChunk {
  timestamp: [number, number];
  text: string;
}

export interface ImportedMediaSummary {
  id: string;
  type: string;
  series: string;
  title: string;
  season: number | null;
  episode: number | null;
  language: string;
  duration: number;
  transcriptionModel: string | null;
  timebase: string | null;
  importedAt: string;
}

export interface ImportedMedia extends ImportedMediaSummary {
  chunks: TranscriptChunk[];
}

export interface MediaImportRequest {
  series: string;
  language: string;
  chunks: TranscriptChunk[];
  title?: string | null;
  season?: number | null;
  episode?: number | null;
  media_type?: string;
  model?: string | null;
  timebase?: string | null;
  audio_seconds?: number | null;
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function errorMessage(response: Response, fallback: string) {
  try {
    const body = await response.json();
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function listImportedMedia(language: string): Promise<ImportedMediaSummary[]> {
  const response = await fetch(`${apiUrl}/api/media?language=${encodeURIComponent(language)}`);
  if (!response.ok) throw new Error(await errorMessage(response, 'Unable to load imported media'));
  const data = await response.json();
  return data.media;
}

export async function getImportedMedia(mediaId: string, language: string): Promise<ImportedMedia> {
  const response = await fetch(`${apiUrl}/api/media/${encodeURIComponent(mediaId)}?language=${encodeURIComponent(language)}`);
  if (!response.ok) throw new Error(await errorMessage(response, 'Unable to load this episode'));
  const data = await response.json();
  return data.media;
}

export async function importMedia(request: MediaImportRequest): Promise<ImportedMedia> {
  const response = await fetch(`${apiUrl}/api/media/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorMessage(response, 'Unable to import media'));
  // POST returns the media directly, unlike both GET endpoints.
  return response.json();
}
