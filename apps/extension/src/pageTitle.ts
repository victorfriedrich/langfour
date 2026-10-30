/**
 * Page titles usually end in the site name ("Madrid - Wikipedia, la
 * enciclopedia libre"). Drops that last part when it names the site, for the
 * reader's heading and the popup's "Read this page" button.
 */
export function cleanTitle(title: string | null | undefined, source: string | null): string | null {
  if (!title) return null;
  const parts = title.split(/\s+[-|–—·:]\s+/);
  if (parts.length < 2 || !source) return title;
  const last = parts[parts.length - 1].toLowerCase();
  const siteWord = source.toLowerCase().replace(/^www\./, '').split('.').filter((p) => p.length > 3)[0] ?? source.toLowerCase();
  return last.includes(siteWord) || siteWord.includes(last) ? parts.slice(0, -1).join(' - ') : title;
}

export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}

// Lyrics read like articles to the extractor. Pages that declare their song
// as schema.org data need no list; these are for the ones that do not.
const LYRICS_HOSTS = ['genius.com', 'letras.com', 'letras.mus.br', 'musixmatch.com', 'azlyrics.com', 'lyrics.com', 'songtexte.com', 'paroles.net', 'testitesti.org', 'angolotesti.it'];

export function isLyricsPage(url: string | null | undefined): boolean {
  const host = hostOf(url);
  return Boolean(host && LYRICS_HOSTS.some((h) => host === h || host.endsWith(`.${h}`)));
}
