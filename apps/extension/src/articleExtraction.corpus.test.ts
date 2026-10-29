// @vitest-environment jsdom
// Runs the reader's extraction over real pages and writes what came out, for
// review. Opt-in, because it needs the pages fetched first:
//
//   node scripts/fetch-reader-corpus.mjs
//   npm run test:corpus
//
// The test fails when a page yields no article or too little of one. The
// report (.corpus-cache/report.md) and the extracted pages
// (.corpus-cache/out/<name>.html) are for reading: they list short blocks and
// boilerplate-like lines, which is where extraction mistakes show up.
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { extractArticle } from './articleExtraction';

const cacheDir = join(__dirname, '..', '.corpus-cache');
const outDir = join(cacheDir, 'out');
const pages = existsSync(cacheDir)
  ? readdirSync(cacheDir).filter((file) => file.endsWith('.html')).sort()
  : [];
const enabled = Boolean(process.env.READER_CORPUS) && pages.length > 0;

/** Pages listed with "none" in urls.txt are not articles; the reader should say so. */
const notArticles = new Set(
  readFileSync(join(__dirname, '..', 'test', 'reader-corpus', 'urls.txt'), 'utf8')
    .split('\n')
    .map((line) => line.trim().split(/\s+/))
    .filter((fields) => fields[0] && !fields[0].startsWith('#') && fields[3] === 'none')
    .map((fields) => fields[0]),
);

/** Words that mark site furniture rather than article text, in the corpus languages. For the report only. */
const BOILERPLATE = /newsletter|suscr[ií]b|cookies?\b|comparte|s[ií]guenos|lee también|te puede interesar|relacionad|publicidad|anuncio|abonnez|lire aussi|newsletter|iscriviti|leggi anche|abonnieren|mehr zum thema|lesen sie auch|werbung|related|advertisement/i;

// Short news items (an ANSA brief, BBC's video stories) run 90 to 150 words.
const MIN_WORDS = 80;

type Row = { name: string; words: number; paragraphs: number; headings: number; images: number; notes: string[] };
const rows: Row[] = [];

function parse(html: string): { doc: Document; url: string } {
  const url = /<!-- corpus-url: (\S+) -->/.exec(html)?.[1] ?? 'https://example.com/';
  // jsdom, not the project's happy-dom: happy-dom's parser stops partway
  // through large real-world pages (El Tiempo lost its whole article body).
  // jsdom parses like a browser and fetches and runs nothing by default.
  const doc = new DOMParser().parseFromString(html, 'text/html');
  // Resolve relative links and images as the live page would.
  const base = doc.createElement('base');
  base.href = url;
  doc.head.prepend(base);
  return { doc, url };
}

describe.skipIf(!enabled)('reader corpus', () => {
  mkdirSync(outDir, { recursive: true });

  for (const file of pages) {
    const name = file.replace(/\.html$/, '');
    // Long Wikipedia articles take a few seconds in jsdom.
    it(name, { timeout: 60_000 }, () => {
      const { doc, url } = parse(readFileSync(join(cacheDir, file), 'utf8'));
      const article = extractArticle(doc, { url });
      if (notArticles.has(name)) {
        expect(article, 'scraps of a page that is not an article').toBeNull();
        return;
      }
      expect(article, 'no article found').not.toBeNull();

      const content = new DOMParser().parseFromString(`<div>${article!.content}</div>`, 'text/html').body;
      const text = content.textContent || '';
      const words = text.trim().split(/\s+/).filter(Boolean).length;
      const notes: string[] = [];
      content.querySelectorAll('p, li, div, h2, h3, h4, figcaption').forEach((el) => {
        if (el.querySelector('p, li, div, h2, h3, h4')) return;
        const line = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!line) return;
        if (line.split(' ').length <= 5 && !/^H\d$/.test(el.tagName)) notes.push(`short <${el.tagName.toLowerCase()}>: ${line}`);
        else if (BOILERPLATE.test(line)) notes.push(`boilerplate? <${el.tagName.toLowerCase()}>: ${line.slice(0, 140)}`);
      });
      rows.push({
        name,
        words,
        paragraphs: content.querySelectorAll('p').length,
        headings: content.querySelectorAll('h2, h3, h4').length,
        images: content.querySelectorAll('img').length,
        notes,
      });

      writeFileSync(join(outDir, `${name}.html`), `<!doctype html><meta charset="utf-8">
<style>body{font:17px/1.6 Georgia,serif;max-width:680px;margin:2em auto;padding:0 1em}img{max-width:100%}
header{font:14px system-ui;color:#666;border-bottom:1px solid #ddd;margin-bottom:1em}</style>
<header>${url}<br>${words} words · ${article!.byline ?? ''} · ${article!.siteName ?? ''}</header>
<h1>${article!.title ?? ''}</h1>${article!.content}`);

      expect(words, 'too little text').toBeGreaterThanOrEqual(MIN_WORDS);
      expect(article!.title, 'no title').toBeTruthy();
    });
  }

  afterAll(() => {
    const lines = ['# Reader corpus', '', '| page | words | paragraphs | headings | images | notes |', '|---|---|---|---|---|---|'];
    for (const r of rows) lines.push(`| ${r.name} | ${r.words} | ${r.paragraphs} | ${r.headings} | ${r.images} | ${r.notes.length} |`);
    for (const r of rows.filter((row) => row.notes.length)) {
      lines.push('', `## ${r.name}`, ...r.notes.map((n) => `- ${n}`));
    }
    writeFileSync(join(cacheDir, 'report.md'), lines.join('\n') + '\n');
  });
});
