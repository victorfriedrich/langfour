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
