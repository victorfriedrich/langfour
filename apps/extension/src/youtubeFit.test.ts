import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BackgroundMessage } from './messages';
import type { VideoFit } from './videoFit';
import { FIT_CACHE_KEY } from './videoFit';
import { FitBadges, percentLabel, startFitBadges } from './youtubeFit';

// Cards from saved YouTube pages, with the background answering from `fits`.
function load(page: string, fits: Record<string, VideoFit>) {
  document.body.innerHTML = readFileSync(join(__dirname, '../test/youtube', page), 'utf8');
  const sent: BackgroundMessage[] = [];
  chrome.runtime.sendMessage = vi.fn((message: BackgroundMessage, respond: (r: unknown) => void) => {
    sent.push(message);
    if (message.type === 'VIDEO_FIT') {
      respond({ ok: true, videos: Object.fromEntries(message.videoIds.map((id) => [id, fits[id] ?? { status: 'unindexed' }])) });
    } else if (message.type === 'QUEUE_VIDEO') {
      respond({ ok: true, status: 'pending' });
    }
  }) as unknown as typeof chrome.runtime.sendMessage;
  return sent;
}

const badge = (videoId: string) => document.querySelector<HTMLElement>(`.langfour-fit[data-video-id="${videoId}"]`);

let badges: FitBadges | undefined;
afterEach(() => badges?.stop());

describe('fit badges', () => {
  it('show the percentage on each card, with new words for the hover', async () => {
    const sent = load('watch-sidebar.html', {
      zrSyyNugKYo: { status: 'scored', percentUnderstood: 97.6, newWords: 12 },
      'DZ-DkAtQrGo': { status: 'hidden' },
    });
    badges = startFitBadges(() => 'es');

    await vi.waitFor(() => expect(badge('zrSyyNugKYo')).not.toBeNull());
    const shown = badge('zrSyyNugKYo')!;
    expect(shown.textContent).toBe('97%· 12 new');
    expect(shown.querySelector('.langfour-fit-more')!.textContent).toBe('· 12 new');
    expect(shown.parentElement!.tagName).toBe('YT-THUMBNAIL-VIEW-MODEL');
    // Hidden by the quality filter: no number at all.
    expect(badge('DZ-DkAtQrGo')).toBeNull();
    expect(sent).toEqual([{ type: 'VIDEO_FIT', language: 'es', videoIds: ['zrSyyNugKYo', 'DZ-DkAtQrGo'] }]);
  });

  it('offer "+ Add" for a video not indexed yet, and queue it without opening it', async () => {
    const sent = load('search.html', {});
    badges = startFitBadges(() => 'es');

    await vi.waitFor(() => expect(badge('vWySIREExjo')).not.toBeNull());
    const add = badge('vWySIREExjo') as HTMLButtonElement;
    expect(add.textContent).toBe('+ Add');
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    add.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);

    await vi.waitFor(() => expect(badge('vWySIREExjo')!.textContent).toBe('Queued'));
    expect((badge('vWySIREExjo') as HTMLButtonElement).disabled).toBe(true);
    expect(sent.at(-1)).toEqual({ type: 'QUEUE_VIDEO', language: 'es', videoId: 'vWySIREExjo' });
  });

  it('redraw every card when the background clears its cache', async () => {
    let percent = 80;
    const sent = load('home.html', {});
    chrome.runtime.sendMessage = vi.fn((message: BackgroundMessage, respond: (r: unknown) => void) => {
      sent.push(message);
      respond({ ok: true, videos: { HmntX1uDjKs: { status: 'scored', percentUnderstood: percent, newWords: 3 } } });
    }) as unknown as typeof chrome.runtime.sendMessage;
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(badge('HmntX1uDjKs')?.firstChild?.textContent).toBe('80%'));

    percent = 85;
    const [listener] = vi.mocked(chrome.storage.onChanged.addListener).mock.calls.at(-1)!;
    listener({ [FIT_CACHE_KEY]: { oldValue: { clearedAt: 0 }, newValue: { clearedAt: 1 } } }, 'local');
    await vi.waitFor(() => expect(badge('HmntX1uDjKs')?.firstChild?.textContent).toBe('85%'));
    expect(sent).toHaveLength(2);
  });

  it('show nothing until a language is known', async () => {
    const sent = load('home.html', {});
    badges = startFitBadges(() => null);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(sent).toEqual([]);
    expect(document.querySelector('.langfour-fit')).toBeNull();
  });
});

describe('percentLabel', () => {
  it('never rounds up to everything', () => {
    expect(percentLabel(99.6)).toBe('99%');
    expect(percentLabel(100)).toBe('100%');
  });
});
