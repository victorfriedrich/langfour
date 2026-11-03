// Checks the YouTube selectors against youtube.com as it is today, signed out,
// in headless Chrome. The saved pages in test/youtube/ only show that the
// selectors fit the markup YouTube had when they were captured; this notices
// when YouTube moves on. Opt-in, because it needs the network and Chrome:
//
//   npm run test:youtube
//
// It runs daily in CI (.github/workflows/youtube-selectors.yml). A failure
// names the page and the selector that found nothing. Recapture that page
// (test/youtube/README.md) and fix youtubeSelectors.ts or youtubeChannel.ts.
//
// Signed out, Home has no feed, so it isn't checked; channel Videos tabs use
// the same cards. CHROME_PATH picks the browser; otherwise the installed
// Google Chrome is used.
import { chromium, type Browser, type Page } from 'playwright-core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { BROWSE, SELECTORS } from './youtubeChannel';
import { findVideoCards } from './youtubeSelectors';

const enabled = Boolean(process.env.YOUTUBE_LIVE);

const SEARCH = 'https://www.youtube.com/results?search_query=aprender+espa%C3%B1ol&hl=es';
// A Spanish channel with years of uploads, like the ones learners favourite.
const CHANNEL = 'https://www.youtube.com/@DreamingSpanish/videos?hl=es';
// Enough cards that a page which half-rendered still passes, and few enough
// that YouTube serving a shorter page doesn't fail it.
const MIN_CARDS = 3;
const TIMEOUT_MS = 90_000;

// "Reject all" on Google's consent page, which EU visitors get before any
// YouTube page. US runners don't see it; a run from Europe would.
const CONSENT = { name: 'SOCS', value: 'CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg', domain: '.youtube.com', path: '/' };

let browser: Browser;

async function open(url: string, waitFor: string): Promise<Page> {
  const context = await browser.newContext({ locale: 'es-ES', viewport: { width: 1400, height: 1000 } });
  await context.addCookies([CONSENT]);
  const page = await context.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector(waitFor, { timeout: 30_000 });
  // Duration labels render after the cards; findVideoCards skips cards without one.
  await page.waitForFunction(() => document.querySelector('.ytBadgeShapeText, ytd-thumbnail-overlay-time-status-renderer #text'), null, { timeout: 15_000 }).catch(() => {});
  return page;
}

/**
 * The page's DOM as the content script sees it, in a document the tests can
 * query. Without what happy-dom would load (frames, scripts, images), which
 * the selectors don't look at.
 */
async function snapshot(page: Page): Promise<Document> {
  const html = await page.evaluate(() => {
    const body = document.body.cloneNode(true) as HTMLElement;
    body.querySelectorAll('iframe, script, link, style, img, video, source, object, embed').forEach((el) => el.remove());
    return body.innerHTML;
  });
  const doc = document.implementation.createHTMLDocument('youtube');
  doc.body.innerHTML = html;
  return doc;
}

describe.skipIf(!enabled)('YouTube selectors on youtube.com', () => {
  beforeAll(async () => {
    browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' });
  }, TIMEOUT_MS);
  afterAll(async () => {
    await browser?.close();
  });

  let watchUrl: string | null = null;

  it('find video cards in search results', async () => {
    const page = await open(SEARCH, 'ytd-video-renderer');
    const cards = findVideoCards(await snapshot(page));
    expect(cards.length, 'video cards found in search results').toBeGreaterThanOrEqual(MIN_CARDS);
    watchUrl = `https://www.youtube.com/watch?v=${cards[0].videoId}&hl=es`;
  }, TIMEOUT_MS);

  it('find video cards in the watch page sidebar', async () => {
    expect(watchUrl, 'a video from the search test').not.toBeNull();
    const page = await open(watchUrl!, '#related yt-lockup-view-model, #related ytd-compact-video-renderer');
    const doc = await snapshot(page);
    const related = doc.querySelector('#related');
    expect(findVideoCards(related ?? doc).length, 'video cards found in the sidebar').toBeGreaterThanOrEqual(MIN_CARDS);
  }, TIMEOUT_MS);

  it('find video cards and the header parts on a channel page', async () => {
    const page = await open(CHANNEL, `${BROWSE} ytd-rich-item-renderer`);
    expect(findVideoCards(await snapshot(page)).length, 'video cards on the Videos tab').toBeGreaterThanOrEqual(MIN_CARDS);

    // The Favourite button and the Langfour tab go into these.
    for (const [name, selector] of Object.entries(SELECTORS)) {
      expect(await page.locator(selector).count(), `channel ${name}: ${selector}`).toBeGreaterThan(0);
    }
    expect(await page.locator(`${SELECTORS.tabs} > .ytTabShapeLastTab`).count(), 'the search tab the Langfour tab goes before').toBe(1);

    // A @handle page has the UC id only in YouTube's own data on ytd-browse.
    const externalId = await page.evaluate((browse) => {
      type BrowseData = { metadata?: { channelMetadataRenderer?: { externalId?: unknown } } };
      const el = document.querySelector(browse) as (Element & { data?: BrowseData }) | null;
      return el?.data?.metadata?.channelMetadataRenderer?.externalId ?? null;
    }, BROWSE);
    expect(externalId, 'the channel id in ytd-browse.data').toMatch(/^UC[\w-]{22}$/);
  }, TIMEOUT_MS);
});
