// Turns what the reader is showing into a Library item on the web app: the
// same /api/media/import endpoint the media page uses for episode
// transcripts, with untimed passages instead of subtitle cues.

import { Language } from './languages';
import { hostOf } from './pageTitle';
import { StoredArticle } from './readerArticles';

export type LibraryKind = 'article' | 'song';

/** The reader element a passage came from; plain paragraphs have none. */
export type Block = 'h2' | 'h3' | 'h4' | 'li' | 'blockquote' | 'pre' | 'figcaption';

export interface Passage {
  text: string;
  block?: Block;
}

export interface LibraryImport {
  media_type: LibraryKind;
  language: Language;
  title: string;
  site: string | null;
  artist: string | null;
  source_url: string | null;
  chunks: Passage[];
}

// Lyrics pages read like articles to the extractor, but belong under Music.
const LYRICS_HOSTS = ['genius.com', 'letras.com', 'letras.mus.br', 'musixmatch.com', 'azlyrics.com', 'lyrics.com', 'songtexte.com', 'paroles.net', 'testitesti.org', 'angolotesti.it'];

export function kindOf(url: string | null | undefined): LibraryKind {
  const host = hostOf(url);
  return host && LYRICS_HOSTS.some((h) => host === h || host.endsWith(`.${h}`)) ? 'song' : 'article';
}

/**
 * `passages` are the visible text of the reader's blocks, in order (one per
 * paragraph, heading, list item or stanza), so the Library can show the text
 * laid out as it was here. Returns null when there is nothing to send.
 */
export function buildLibraryImport(article: StoredArticle, passages: Passage[], language: Language): LibraryImport | null {
  const chunks = passages
    .map(({ text, block }) => ({ text: text.replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim(), ...(block && { block }) }))
    .filter((passage) => passage.text);
  if (chunks.length === 0) return null;
  const kind = kindOf(article.url);
  const site = article.siteName || hostOf(article.url) || null;
  // "Tití Me Preguntó Lyrics" on Genius; the song is the part before.
  const rawTitle = (article.title || '').trim() || chunks[0].text.slice(0, 80);
  const title = kind === 'song' ? rawTitle.replace(/\s+(lyrics|letra|testo|paroles|songtext)$/i, '') : rawTitle;
  return {
    media_type: kind,
    language,
    title,
    site,
    artist: kind === 'song' ? article.byline || null : null,
    source_url: article.url || null,
    chunks,
  };
}

/** The id of an item the API says is already in the Library ("Media already exists: <id>"). */
export function existingIdFrom(body: string): string | null {
  try {
    const detail = JSON.parse(body).detail;
    return typeof detail === 'string' ? detail.match(/already exists: ([\w-]+)/)?.[1] ?? null : null;
  } catch {
    return null;
  }
}
