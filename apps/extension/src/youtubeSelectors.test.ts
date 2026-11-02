import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { findVideoCards, videoIdFromHref } from './youtubeSelectors';

// Saved YouTube pages (test/youtube/README.md). A failure here after a
// recapture means YouTube changed its markup and youtubeSelectors.ts needs
// to follow.
function page(name: string): Document {
  const doc = document.implementation.createHTMLDocument('youtube');
  doc.body.innerHTML = readFileSync(join(__dirname, '../test/youtube', name), 'utf8');
  return doc;
}

const found = (name: string) =>
  findVideoCards(page(name)).map(({ videoId, card, box }) => ({
    videoId,
    card: card.tagName.toLowerCase(),
    box: box.tagName.toLowerCase(),
  }));

describe('YouTube selectors against saved pages', () => {
  it('find the video cards on Home and skip Shorts', () => {
    expect(found('home.html')).toEqual([
      { videoId: 'HmntX1uDjKs', card: 'yt-lockup-view-model', box: 'yt-thumbnail-view-model' },
    ]);
  });

  it('find search results and skip live streams and Shorts', () => {
    expect(found('search.html')).toEqual([
      { videoId: 'vWySIREExjo', card: 'ytd-video-renderer', box: 'ytd-thumbnail' },
    ]);
  });

  it('find the watch page sidebar cards', () => {
    expect(found('watch-sidebar.html')).toEqual([
      { videoId: 'zrSyyNugKYo', card: 'yt-lockup-view-model', box: 'yt-thumbnail-view-model' },
      { videoId: 'DZ-DkAtQrGo', card: 'yt-lockup-view-model', box: 'yt-thumbnail-view-model' },
    ]);
  });

  it('ignore thumbnails outside the known cards', () => {
    const doc = page('watch-sidebar.html');
    const panel = doc.createElement('ytd-playlist-panel-video-renderer');
    const link = doc.querySelector('a.ytLockupViewModelContentImage')!.cloneNode(true);
    panel.appendChild(link);
    doc.body.replaceChildren(panel);
    expect(findVideoCards(doc)).toEqual([]);
  });
});

describe('videoIdFromHref', () => {
  it('reads watch links only', () => {
    expect(videoIdFromHref('/watch?v=vWySIREExjo&pp=ygUX')).toBe('vWySIREExjo');
    expect(videoIdFromHref('https://www.youtube.com/watch?v=DZ-DkAtQrGo&list=RD1&index=2')).toBe('DZ-DkAtQrGo');
    expect(videoIdFromHref('/shorts/tv6dko84kcM')).toBeNull();
    expect(videoIdFromHref('/watch?v=short')).toBeNull();
    expect(videoIdFromHref(null)).toBeNull();
  });
});
