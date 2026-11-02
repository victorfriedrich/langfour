import { describe, expect, it } from 'vitest';
import { consentText, dayOf, historyState, parseHistoryPage } from './watchHistory';

// A history page as YouTube serves it, cut down to what the parser reads:
// ytcfg with the account and language, and ytInitialData with sections of
// videos in both the old (videoRenderer) and new (lockupViewModel) shapes.
function page(data: unknown, { loggedIn = true, hl = 'en' } = {}): string {
  return `<html><script>ytcfg.set({"LOGGED_IN":${loggedIn},"DATASYNC_ID":"acc123||","HL":"${hl}"});</script>` +
    `<script>var ytInitialData = ${JSON.stringify(data)};</script></html>`;
}

const section = (title: string, ...contents: unknown[]) => ({
  itemSectionRenderer: {
    header: { itemSectionHeaderRenderer: { title: { runs: [{ text: title }] } } },
    contents,
  },
});
const oldVideo = (videoId: string, percent?: number) => ({
  videoRenderer: {
    videoId,
    title: { runs: [{ text: 'A title with } and { in it' }] },
    thumbnailOverlays: percent === undefined ? [] : [{ thumbnailOverlayResumePlaybackRenderer: { percentDurationWatched: percent } }],
  },
});
const newVideo = (contentId: string, percent?: number) => ({
  lockupViewModel: {
    contentId,
    contentType: 'LOCKUP_CONTENT_TYPE_VIDEO',
    contentImage: { thumbnailViewModel: { overlays: percent === undefined ? [] : [{
      thumbnailBottomOverlayViewModel: { progressBar: { thumbnailOverlayProgressBarViewModel: { startPercent: percent } } },
    }] } },
  },
});
const data = (...sections: unknown[]) => ({
  contents: { twoColumnBrowseResultsRenderer: { tabs: [{ tabRenderer: { content: { sectionListRenderer: { contents: sections } } } }] } },
});

describe('parseHistoryPage', () => {
  it('reads each video with its red bar and day', () => {
    const html = page(data(
      section('Today', oldVideo('aaaaaaaaaaa', 45), newVideo('bbbbbbbbbbb', 100)),
      section('Yesterday', newVideo('ccccccccccc')),
      section('Oct 25', oldVideo('ddddddddddd', 80)),
    ));
    expect(parseHistoryPage(html)).toEqual({
      account: 'acc123||',
      items: [
        { video_id: 'aaaaaaaaaaa', share: 0.45, day: 0 },
        { video_id: 'bbbbbbbbbbb', share: 1, day: 0 },
        { video_id: 'ccccccccccc', share: null, day: 1 },
        { video_id: 'ddddddddddd', share: 0.8, day: null },
      ],
    });
  });

  it('keeps the latest watch of a video seen twice', () => {
    const html = page(data(section('Today', oldVideo('aaaaaaaaaaa', 20)), section('Yesterday', oldVideo('aaaaaaaaaaa', 100))));
    expect(parseHistoryPage(html).items).toEqual([{ video_id: 'aaaaaaaaaaa', share: 0.2, day: 0 }]);
  });

  it('reads the day in the page language', () => {
    const html = page(data(section('Hoy', oldVideo('aaaaaaaaaaa')), section('Ayer', oldVideo('bbbbbbbbbbb'))), { hl: 'es' });
    expect(parseHistoryPage(html).items.map((i) => i.day)).toEqual([0, 1]);
    expect(dayOf('Gestern', 'de')).toBe(1);
    expect(dayOf('Montag', 'de')).toBeNull();
  });

  it('reads nothing when signed out or the data is missing', () => {
    expect(parseHistoryPage(page(data(section('Today', oldVideo('aaaaaaaaaaa'))), { loggedIn: false })))
      .toEqual({ account: null, items: [] });
    expect(parseHistoryPage('<html></html>')).toEqual({ account: null, items: [] });
    expect(parseHistoryPage(page({})).items).toEqual([]);
  });
});

describe('historyState', () => {
  it('asks until answered, and again for a new account', () => {
    expect(historyState({})).toBe('ask');
    expect(historyState({ historyConsent: ['a'] })).toBe('on');
    expect(historyState({ historyConsent: [], historyDeclined: true })).toBe('off');
    expect(historyState({ historyConsent: ['a'], historyNewAccount: true })).toBe('ask');
  });

  it('says what happens to the ids', () => {
    expect(consentText('Spanish')).toBe(
      'The video ids on your YouTube history page are checked against Langfour\'s Spanish library, and only matches are kept.',
    );
  });
});
