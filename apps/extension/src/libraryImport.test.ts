import { describe, expect, it } from 'vitest';
import { buildLibraryImport, existingIdFrom, kindOf } from './libraryImport';

const article = (over: Record<string, unknown> = {}) => ({ title: 'La economía crece', content: '', url: 'https://elpais.com/economia/1.html', siteName: 'El País', byline: 'Ana Ruiz', savedAt: 0, ...over });

describe('buildLibraryImport', () => {
  it('sends an article as untimed passages, with headings marked, and its source', () => {
    expect(buildLibraryImport(article(), [{ text: 'Titular', block: 'h2' }, { text: '  Primer  párrafo. ' }, { text: '' }, { text: 'Segundo.' }], 'es')).toEqual({
      media_type: 'article', language: 'es', title: 'La economía crece', site: 'El País', artist: null,
      source_url: 'https://elpais.com/economia/1.html', chunks: [{ text: 'Titular', block: 'h2' }, { text: 'Primer párrafo.' }, { text: 'Segundo.' }],
    });
  });

  it('files lyrics pages under songs and keeps stanza line breaks', () => {
    const payload = buildLibraryImport(article({ url: 'https://genius.com/x', title: 'Tití Me Preguntó Lyrics', byline: 'Bad Bunny', siteName: null }), [{ text: 'Línea uno \n  línea dos' }], 'es');
    expect(payload).toMatchObject({ media_type: 'song', title: 'Tití Me Preguntó', artist: 'Bad Bunny', site: 'genius.com', chunks: [{ text: 'Línea uno\nlínea dos' }] });
  });

  it('files a song the reader recognised on any site under songs', () => {
    const payload = buildLibraryImport(article({ url: 'https://blog.example.com/letra', title: 'Calle de noche', byline: 'Los Ejemplos', kind: 'song' }), [{ text: 'Una línea' }], 'es');
    expect(payload).toMatchObject({ media_type: 'song', title: 'Calle de noche', artist: 'Los Ejemplos' });
  });

  it('returns null for an empty page', () => {
    expect(buildLibraryImport(article(), [{ text: ' ' }, { text: '' }], 'es')).toBeNull();
  });
});

describe('helpers', () => {
  it('recognises lyrics hosts including subdomains', () => {
    expect(kindOf('https://www.letras.com/a/b')).toBe('song');
    expect(kindOf('https://es.genius.com/a')).toBe('song');
    expect(kindOf('https://bbc.com/mundo')).toBe('article');
    expect(kindOf(null)).toBe('article');
  });

  it('reads the existing id from a 409', () => {
    expect(existingIdFrom('{"detail":"Media already exists: la-economia-crece-1a2b3c"}')).toBe('la-economia-crece-1a2b3c');
    expect(existingIdFrom('not json')).toBeNull();
  });
});
