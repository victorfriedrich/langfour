// Article extraction for the reader: from a rendered page to clean reading
// HTML. One pipeline, built on what pages declare about themselves rather
// than on per-site selectors:
//
//   1. prune   Drop what the page marks as not being content: scripts and
//              widgets, hidden elements, dialogs (cookie and consent walls),
//              navigation, banners, sidebars; and, where layout is known,
//              fixed overlays and text meant only for screen readers.
//   2. extract Mozilla Readability (Firefox's Reader View) finds the article.
//   3. normalize
//              Keep reading elements only, then drop what Readability let
//              through that is not prose: link-dense blocks (tables of
//              contents, "related" lists), stray labels left by ads and
//              widgets, date and time lines, reference markers, icons and
//              tiny images; and trim the edges, since an article starts and
//              ends with prose: fragments before the first sentence and after
//              the last, and closing promotions (follow us, get the app,
//              subscribe).
//
// Checked against real pages by articleExtraction.corpus.test.ts (see
// test/reader-corpus/README.md) and rule by rule in articleExtraction.test.ts.
import { Readability } from '@mozilla/readability';
import DOMPurify from 'dompurify';
import type { ArticleData } from './messages';
import { cleanTitle, hostOf } from './pageTitle';

export type ExtractOptions = {
  /** The page's address: the article's source, and the base for links. */
  url: string;
  /**
   * Layout facts about elements of the live page, which only the browser
   * can provide (see layoutJudge below). Without it those steps are skipped.
   */
  layout?: (element: Element) => LayoutVerdict;
};

/**
 * 'hidden': not displayed (display: none, visibility: hidden): print-only
 *   notices, collapsed duplicates of the body, menus.
 * 'overlay': floats over the page (position fixed or sticky): cookie bars,
 *   sticky headers, app banners.
 * 'screen-reader-only': clipped to nothing so only assistive technology
 *   reads it ("Image source,", "Author,"); sighted readers never see it.
 */
export type LayoutVerdict = 'hidden' | 'overlay' | 'screen-reader-only' | null;

// ---------------------------------------------------------------------------
// 1. Prune
// ---------------------------------------------------------------------------

/**
 * Elements that are never part of an article, by tag, state or ARIA role.
 * Roles are how pages tell assistive technology what a region is, so they
 * work across sites where class names do not.
 */
const NON_CONTENT_SELECTOR = [
  // Code, embeds and widgets: their text is labels, chart axes or icons.
  'script', 'style', 'noscript', 'template', 'iframe', 'object', 'embed',
  'form', 'button', 'input', 'select', 'textarea', 'svg', 'canvas', 'dialog',
  // Hidden from everyone. Not hidden="until-found": that is collapsed but
  // part of the page (mobile Wikipedia folds every section that way).
  '[hidden]:not([hidden="until-found"])', '[aria-hidden="true"]',
  // Modal layers: cookie and consent walls, subscription prompts.
  '[aria-modal="true"]', '[role="dialog"]', '[role="alertdialog"]',
  // Landmarks that are not the article.
  'nav', 'aside', '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
  '[role="complementary"]', '[role="search"]', '[role="menu"]', '[role="menubar"]',
  '[role="toolbar"]', '[role="tablist"]',
].join(',');

/**
 * A page-level header or footer holds the site's logo, menus and legal
 * links. One inside the article or main region holds its title, byline and
 * lead, which Readability uses, so those stay.
 */
function isPageChrome(element: Element): boolean {
  return !element.parentElement?.closest('article, main, [role="main"]');
}

function prune(doc: Document): void {
  doc.querySelectorAll(NON_CONTENT_SELECTOR).forEach((el) => el.remove());
  // Collapsed, not hidden: Readability skips anything with a hidden
  // attribute, which cost mobile Wikipedia every section after the intro.
  doc.querySelectorAll('[hidden="until-found"]').forEach((el) => el.removeAttribute('hidden'));
  doc.querySelectorAll('header, footer').forEach((el) => {
    if (isPageChrome(el)) el.remove();
  });
}

/**
 * Clones the document without what layout shows is not part of the page's
 * reading flow. Right after cloneNode the two trees match element for
 * element, so a live element that layout can judge maps to its copy by
 * position.
 */
function cloneWithoutLayoutFurniture(doc: Document, layout?: (element: Element) => LayoutVerdict): Document {
  const clone = doc.cloneNode(true) as Document;
  if (!layout || !doc.body || !clone.body) return clone;
  const live = doc.body.getElementsByTagName('*');
  const copy = clone.body.getElementsByTagName('*');
  // Some single-page apps put everything in one fixed container; an overlay
  // floats over the page, it does not hold most of it.
  const pageText = (doc.body.textContent || '').length;
  const furniture: Element[] = [];
  for (let i = 0; i < live.length && i < copy.length; i++) {
    const verdict = layout(live[i]);
    if (verdict === 'hidden' || verdict === 'screen-reader-only') furniture.push(copy[i]);
    if (verdict === 'overlay' && (live[i].textContent || '').length < pageText / 2) furniture.push(copy[i]);
  }
  furniture.forEach((el) => el.remove());
  return clone;
}

// ---------------------------------------------------------------------------
// 3. Normalize
// ---------------------------------------------------------------------------

const READING_TAGS = [
  'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'blockquote', 'q', 'figure', 'figcaption', 'img', 'picture', 'source', 'a',
  'em', 'i', 'strong', 'b', 'u', 's', 'sub', 'sup', 'small', 'mark', 'abbr', 'cite',
  'code', 'pre', 'kbd', 'hr', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
  'caption', 'div', 'span', 'section', 'article', 'time',
];
const READING_ATTRIBUTES = [
  'href', 'src', 'srcset', 'sizes', 'alt', 'title', 'width', 'height',
  'colspan', 'rowspan', 'datetime', 'lang', 'dir',
];

const BLOCKS = 'p, div, section, article, ul, ol, dl, li, table, blockquote, figure, h1, h2, h3, h4, h5, h6, pre';

function wordsIn(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Share of a block's text that sits inside links. Navigation is mostly
 * links (tables of contents, "related" and "more on" lists, tag clouds);
 * prose has a few. Readability scores candidates with the same measure.
 */
function linkDensity(element: Element): number {
  const text = (element.textContent || '').replace(/\s+/g, '').length;
  if (text === 0) return 0;
  let linked = 0;
  element.querySelectorAll('a').forEach((a) => {
    linked += (a.textContent || '').replace(/\s+/g, '').length;
  });
  return linked / text;
}

function removeLinkDenseBlocks(root: ParentNode): void {
  // Innermost first, so a list inside an otherwise good section goes on its
  // own and the section is judged without it.
  const blocks = Array.from(root.querySelectorAll('ul, ol, dl, table, section, div, p')).reverse();
  for (const block of blocks) {
    // Already gone with an ancestor. (Not isConnected: inside a detached
    // fragment that is false for everything.)
    if (!root.contains(block)) continue;
    const links = block.querySelectorAll('a').length;
    const density = linkDensity(block);
    const isList = /^(UL|OL|DL|TABLE|SECTION|DIV)$/.test(block.tagName);
    // Lists and sections of several links, or a paragraph that is nothing
    // but a link ("Read more: …").
    if ((isList && links >= 3 && density >= 0.6) || (!isList && links >= 1 && density >= 0.9)) {
      block.remove();
    }
  }
}

/**
 * Prose is made of sentences. A block of one to three words with no digits
 * and no sentence punctuation, outside lists, tables, captions and quotes,
 * is a label: the "PUBLICIDAD" an ad slot leaves behind, a section kicker
 * ("Análisis"), a widget's leftover title. Headings are kept.
 */
function removeStrayLabels(root: ParentNode): void {
  root.querySelectorAll('p, div').forEach((block) => {
    if (block.querySelector(BLOCKS) || block.querySelector('img, picture')) return;
    if (block.closest('li, td, th, figcaption, blockquote, dd, dt')) return;
    const text = (block.textContent || '').trim();
    if (!text) return;
    if (wordsIn(text) <= 3 && !/[\d.!?…:;"“”«»]/.test(text)) block.remove();
  });
}

/**
 * Endnote and reference lists: items that start with a back-link arrow
 * (Wikipedia's "↑", footnotes generated from Markdown "↩"). Their markers
 * in the text are removed above, so the notes have nothing to point back to.
 */
function removeEndnoteLists(root: ParentNode): void {
  root.querySelectorAll('ol, ul').forEach((list) => {
    const items = Array.from(list.children).filter((el) => el.tagName === 'LI');
    if (items.length < 2) return;
    const notes = items.filter((li) => /^\s*[↑^↩]/.test(li.textContent || '')).length;
    if (notes / items.length >= 0.6) list.remove();
  });
}

/** Reference markers like [9] or [nota 1]: noise when reading for language. */
function removeReferenceMarkers(root: ParentNode): void {
  root.querySelectorAll('sup').forEach((sup) => {
    if (/^\s*(\[[^\]]{1,15}\]\s*)+$/.test(sup.textContent || '')) sup.remove();
  });
}

const MIN_IMAGE_SIDE = 64;

/** Icons, flags, avatars and tracking pixels, judged by their declared size. */
function removeSmallImages(root: ParentNode): void {
  root.querySelectorAll('img').forEach((img) => {
    const width = Number(img.getAttribute('width')) || Infinity;
    const height = Number(img.getAttribute('height')) || Infinity;
    if (!img.getAttribute('src') || width < MIN_IMAGE_SIDE || height < MIN_IMAGE_SIDE) img.remove();
  });
}

/** Icon fonts put glyphs in the private use area; zero-width characters split words. */
function cleanText(root: Node): void {
  const doc = root.ownerDocument ?? (root as Document);
  const walker = doc.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = node.nodeValue || '';
    if (/[\uE000-\uF8FF\u200B-\u200D\u2060\uFEFF]/.test(value)) {
      node.nodeValue = value.replace(/[\uE000-\uF8FF\u200B-\u200D\u2060\uFEFF]/g, '');
    }
  }
}

/**
 * The reader shows the title in its own header, so a heading at the top of
 * the content that repeats it goes, and other h1s become h2s.
 */
function normalizeHeadings(root: ParentNode, title: string | null): void {
  const first = root.querySelector('h1, h2');
  const normalized = (s: string) => s.toLowerCase().replace(/\s+/g, ' ').trim();
  if (first && title && normalized(first.textContent || '') === normalized(title)) first.remove();
  root.querySelectorAll('h1').forEach((h1) => {
    const h2 = h1.ownerDocument.createElement('h2');
    h2.append(...Array.from(h1.childNodes));
    h1.replaceWith(h2);
  });
}

/** Blocks emptied by the steps above. Inline elements stay: a whitespace-only span can be the only space between two words. */
function removeEmptyBlocks(root: ParentNode): void {
  let removed = true;
  while (removed) {
    removed = false;
    root.querySelectorAll('p, div, section, article, figure, ul, ol, li, blockquote, table').forEach((el) => {
      if (!el.textContent?.trim() && !el.querySelector('img, picture')) {
        el.remove();
        removed = true;
      }
    });
  }
}

const CLOCK_TIME = /\b\d{1,2}:\d{2}\b/;
const NUMERIC_DATE = /\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b/;
const MAX_METADATA_WORDS = 12;

/**
 * Datelines and timestamps ("06/10/2026 06:00 Actualizado 15:45"): short
 * lines carrying a clock time or a numeric date. The reader has its own
 * header. Not in lists, where a time can start real content (a podcast's
 * chapter list: "49:20 — …").
 */
function removeMetadataLines(root: ParentNode): void {
  root.querySelectorAll('p, div, span, time').forEach((block) => {
    if (block.querySelector(BLOCKS) || block.closest('li, td, th, figcaption')) return;
    const text = (block.textContent || '').trim();
    if (text && wordsIn(text) <= MAX_METADATA_WORDS && (CLOCK_TIME.test(text) || NUMERIC_DATE.test(text))) {
      block.remove();
    }
  });
}

/** The units the edge trimming looks at: the innermost text blocks, plus tables and figures whole. */
const UNIT = 'p, li, h2, h3, h4, h5, h6, figcaption, pre, dt, dd, div, table, figure, blockquote';

function readingUnits(root: ParentNode): Element[] {
  return Array.from(root.querySelectorAll(UNIT)).filter((el) => {
    if (el.parentElement?.closest('table, figure')) return false;
    if (el.matches('table, figure')) return true;
    return !el.querySelector(UNIT) && Boolean((el.textContent || '').trim());
  });
}

const SENTENCE_END = /[.!?…:;"”»)\]]$/;

/**
 * A sentence, or near enough: long, or ending like one. Figures and tables
 * are structure. So is a heading at the start, but not at the end: a heading
 * with nothing after it is what is left of a removed section.
 */
function isProse(unit: Element, edge: 'start' | 'end'): boolean {
  if (/^(FIGURE|TABLE)$/.test(unit.tagName)) return true;
  if (/^H\d$/.test(unit.tagName)) return edge === 'start';
  const text = (unit.textContent || '').trim();
  const words = wordsIn(text);
  return words >= 8 || (words >= 3 && SENTENCE_END.test(text));
}

/**
 * Where a closing block's links go when it promotes the publisher rather
 * than continuing the article: social networks, app stores and app-link
 * services, Google News and Google's "preferred source" setting, and the
 * site's own newsletter and subscription pages.
 */
const PROMOTION_HOSTS = /(^|\.)(facebook|instagram|tiktok|twitter|x|youtube|whatsapp|telegram|t|linkedin|threads|bsky|pinterest|flipboard)\.(com|me|app|org)$|^news\.google\.|^(apps|itunes)\.apple\.com$|^play\.google\.com$|(^|\.)(onelink\.me|app\.link|page\.link|adj\.st)$/i;
const PROMOTION_PATHS = /newsletter|suscri|subscri|abonn|abbona|abonnier|registr|signup|sign-up|^\/preferences\/source/i;
const MAX_PROMOTION_WORDS = 80;

function isPromotionLink(link: Element): boolean {
  try {
    const url = new URL(link.getAttribute('href') || '', 'https://invalid.example/');
    return PROMOTION_HOSTS.test(url.hostname) || PROMOTION_PATHS.test(url.pathname);
  } catch {
    return false;
  }
}

/** Set before Readability on blocks around promotion links (see markPromotions). */
const PROMOTION_MARK = 'data-langfour-promotion';

function isPromotion(block: Element): boolean {
  if (wordsIn(block.textContent || '') > MAX_PROMOTION_WORDS) return false;
  if (block.matches(`[${PROMOTION_MARK}]`) || block.querySelector(`[${PROMOTION_MARK}]`)) return true;
  if (linkDensity(block) >= 0.5) return true;
  return Array.from(block.querySelectorAll('a[href]')).some(isPromotionLink);
}

/**
 * Readability drops link-heavy bits such as a card's "follow us" button,
 * which is the only sign the card was a promotion. So before it runs, the
 * short block around each promotion link is marked. The mark removes
 * nothing by itself: an article paragraph may link to a tweet or a video.
 * trimEdges only acts on marked blocks left at the end of the article.
 */
function markPromotions(doc: Document): void {
  doc.querySelectorAll('a[href]').forEach((link) => {
    if (isPromotionLink(link)) surroundingShortBlock(link).setAttribute(PROMOTION_MARK, '');
  });
}

/**
 * The largest block around a unit that is still short: the card or list a
 * closing line belongs to. Promotions come as such blocks (a "follow us"
 * card whose button is a separate paragraph, a list of "get the app",
 * "follow us", "subscribe"), so they are judged whole.
 */
function surroundingShortBlock(unit: Element): Element {
  let block = unit;
  while (block.parentElement && wordsIn(block.parentElement.textContent || '') <= MAX_PROMOTION_WORDS) {
    block = block.parentElement;
  }
  return block;
}

/**
 * An article starts and ends with prose. Before the first sentence sit
 * kickers, datelines and "Reading time: 3 min"; after the last, tags, credits,
 * comment counts and promotions (follow us, get the app, subscribe, more from
 * this site). Trims both edges, stopping at the first unit of real text.
 */
function trimEdges(root: ParentNode): void {
  for (const unit of readingUnits(root)) {
    // A lead image does not end the preamble; its caption is not prose either.
    if (unit.matches('figure')) continue;
    if (isProse(unit, 'start')) break;
    unit.remove();
  }
  const units = readingUnits(root);
  for (let i = units.length - 1; i >= 0; i--) {
    const unit = units[i];
    if (!root.contains(unit) || unit.matches('figure')) continue;
    const block = surroundingShortBlock(unit);
    if (isPromotion(block)) {
      block.remove();
    } else if (!isProse(unit, 'end')) {
      unit.remove();
    } else {
      break;
    }
  }
}

function normalize(html: string, title: string | null): string {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: READING_TAGS,
    ALLOWED_ATTR: [...READING_ATTRIBUTES, PROMOTION_MARK],
    // data-* attributes are on by default; Wikipedia's carry the page's
    // whole source as JSON, which would be stored with every article.
    ALLOW_DATA_ATTR: false,
    RETURN_DOM_FRAGMENT: true,
  }) as DocumentFragment;

  removeReferenceMarkers(clean);
  removeEndnoteLists(clean);
  // Edges first, while closing promotions still have their links: the
  // link-dense rule below would take a card's "follow us" button and leave
  // its text with no sign of what it was.
  trimEdges(clean);
  removeLinkDenseBlocks(clean);
  removeStrayLabels(clean);
  removeMetadataLines(clean);
  removeSmallImages(clean);
  normalizeHeadings(clean, title);
  cleanText(clean);
  removeEmptyBlocks(clean);
  // Again, for fragments the steps above left at an edge.
  trimEdges(clean);
  removeEmptyBlocks(clean);

  clean.querySelectorAll(`[${PROMOTION_MARK}]`).forEach((el) => el.removeAttribute(PROMOTION_MARK));
  const container = clean.ownerDocument.createElement('div');
  container.append(clean);
  return container.innerHTML;
}

// ---------------------------------------------------------------------------
// Recipes
// ---------------------------------------------------------------------------

/**
 * Readability drops recipe ingredient boxes: a block of short list items
 * scores like navigation. Recipe pages declare their ingredients as
 * schema.org Recipe data (what search engines read), so they come from
 * there when the extracted text lacks them.
 */
function recipeIngredients(doc: Document): string[] {
  for (const script of Array.from(doc.querySelectorAll('script[type="application/ld+json"]'))) {
    let data: unknown;
    try {
      data = JSON.parse(script.textContent || '');
    } catch {
      continue;
    }
    const pending: unknown[] = [data];
    while (pending.length) {
      const item = pending.pop();
      if (Array.isArray(item)) {
        pending.push(...item);
        continue;
      }
      if (!item || typeof item !== 'object') continue;
      const record = item as Record<string, unknown>;
      const types = ([] as unknown[]).concat(record['@type']);
      if (types.includes('Recipe') && Array.isArray(record.recipeIngredient)) {
        return record.recipeIngredient
          .filter((ingredient): ingredient is string => typeof ingredient === 'string' && Boolean(ingredient.trim()))
          .map((ingredient) => ingredient.trim());
      }
      if (record['@graph']) pending.push(record['@graph']);
    }
  }
  return [];
}

const INGREDIENTS_HEADING: Record<string, string> = {
  es: 'Ingredientes', pt: 'Ingredientes', de: 'Zutaten', fr: 'Ingrédients', it: 'Ingredienti', en: 'Ingredients',
};

/** Adds the declared ingredients after the article's first paragraph, unless most are already in it. */
function withIngredients(content: string, ingredients: string[], doc: Document): string {
  if (!ingredients.length) return content;
  const container = doc.createElement('div');
  container.innerHTML = content;
  const text = (container.textContent || '').toLowerCase();
  const present = ingredients.filter((ingredient) => text.includes(ingredient.toLowerCase())).length;
  if (present >= ingredients.length / 2) return content;

  const language = (doc.documentElement.lang || 'en').slice(0, 2).toLowerCase();
  const heading = doc.createElement('h2');
  heading.textContent = INGREDIENTS_HEADING[language] ?? INGREDIENTS_HEADING.en;
  const list = doc.createElement('ul');
  for (const ingredient of ingredients) {
    const item = doc.createElement('li');
    item.textContent = ingredient;
    list.append(item);
  }
  const lead = container.querySelector('p');
  if (lead) lead.after(heading, list);
  else container.prepend(heading, list);
  return container.innerHTML;
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

/** Pages shorter than this are not articles; Readability's default is 500. */
const MIN_ARTICLE_CHARS = 500;
/**
 * Readability relaxes its rules when nothing qualifies and then returns
 * whatever it finds, such as a video page's caption. Below this, the reader
 * says there is no article rather than showing scraps.
 */
const MIN_ARTICLE_WORDS = 40;

export function extractArticle(doc: Document, options: ExtractOptions): ArticleData | null {
  const clone = cloneWithoutLayoutFurniture(doc, options.layout);
  prune(clone);
  markPromotions(clone);

  const parsed = new Readability(clone, { charThreshold: MIN_ARTICLE_CHARS }).parse();
  if (!parsed?.content) return null;

  const siteName = parsed.siteName || null;
  const title = cleanTitle(parsed.title, siteName || hostOf(options.url));
  const content = withIngredients(normalize(parsed.content, title), recipeIngredients(doc), doc);
  const probe = doc.createElement('div');
  probe.innerHTML = content;
  if (wordsIn(probe.textContent || '') < MIN_ARTICLE_WORDS) return null;

  return {
    title,
    content,
    byline: parsed.byline || null,
    siteName,
    url: options.url,
  };
}

/** The live page's layout facts for extractArticle, from computed styles. */
export function layoutJudge(element: Element): LayoutVerdict {
  const view = element.ownerDocument.defaultView;
  if (!view) return null;
  // Collapsed sections stay (see prune); everything else not displayed goes.
  if (element.closest('[hidden="until-found"]')) return null;
  const style = view.getComputedStyle(element);
  if (style.display === 'none' || style.visibility === 'hidden') return 'hidden';
  if (style.position === 'fixed' || style.position === 'sticky') return 'overlay';
  // The usual "visually hidden" pattern: absolutely positioned and clipped
  // to nothing, or shrunk to a pixel.
  if (style.position === 'absolute') {
    const clipped = style.clip === 'rect(0px, 0px, 0px, 0px)' || style.clipPath === 'inset(50%)';
    const tiny = parseFloat(style.width) <= 1 && parseFloat(style.height) <= 1 && style.overflow === 'hidden';
    if (clipped || tiny) return 'screen-reader-only';
  }
  return null;
}
