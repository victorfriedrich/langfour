import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BackgroundMessage } from './messages';
import type { QueueStatus, VideoFit } from './videoFit';
import { FIT_CACHE_KEY } from './videoFit';
import { FitBadges, percentLabel, queuedLabel, startFitBadges } from './youtubeFit';

// Cards from saved YouTube pages, with the background answering from `fits`.
function load(page: string, fits: Record<string, VideoFit>, queued: QueueStatus = 'pending') {
  document.body.innerHTML = readFileSync(join(__dirname, '../test/youtube', page), 'utf8');
  const sent: BackgroundMessage[] = [];
  chrome.runtime.sendMessage = vi.fn((message: BackgroundMessage, respond: (r: unknown) => void) => {
    sent.push(message);
    if (message.type === 'VIDEO_FIT') {
      respond({ ok: true, videos: Object.fromEntries(message.videoIds.map((id) => [id, fits[id] ?? { status: 'unindexed' }])) });
    } else if (message.type === 'QUEUE_VIDEO') {
      respond({ ok: true, status: queued });
    }
  }) as unknown as typeof chrome.runtime.sendMessage;
  return sent;
}

const badge = (videoId: string) => document.querySelector<HTMLElement>(`.langfour-fit[data-video-id="${videoId}"]`);
const layer = () => document.querySelector<HTMLElement>('.langfour-fit-layer')!;
const hover = (videoId: string) =>
  document.querySelector(`a[href*="${videoId}"]`)!.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));

let badges: FitBadges | undefined;
afterEach(() => badges?.stop());

describe('fit badges', () => {
  it('show the percentage on each card, and the new words on hover', async () => {
    const sent = load('watch-sidebar.html', {
      zrSyyNugKYo: { status: 'scored', percentUnderstood: 97.6, newWords: 12 },
      'DZ-DkAtQrGo': { status: 'hidden' },
    });
    badges = startFitBadges(() => 'es');

    await vi.waitFor(() => expect(badge('zrSyyNugKYo')).not.toBeNull());
    expect(badge('zrSyyNugKYo')!.textContent).toBe('97%');
    expect(badge('zrSyyNugKYo')!.parentElement!.tagName).toBe('YT-THUMBNAIL-VIEW-MODEL');
    // Hidden by the quality filter: no number at all.
    expect(badge('DZ-DkAtQrGo')).toBeNull();
    expect(sent).toEqual([{ type: 'VIDEO_FIT', language: 'es', videoIds: ['zrSyyNugKYo', 'DZ-DkAtQrGo'] }]);

    hover('zrSyyNugKYo');
    expect(layer().textContent).toBe('97%· 12 new');
    expect(layer().querySelector('.langfour-fit-more')!.textContent).toBe('· 12 new');
    hover('DZ-DkAtQrGo');
    expect(layer().textContent).toBe('');
  });

  it('offer "+ Add" on hover for a video not indexed yet, and queue it', async () => {
    const sent = load('search.html', {});
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(badge('vWySIREExjo')).toBeNull();

    hover('vWySIREExjo');
    const add = layer().querySelector<HTMLButtonElement>('button')!;
    expect(add.textContent).toBe('+ Add');
    add.click();

    await vi.waitFor(() => expect(layer().textContent).toBe('Queued'));
    expect(layer().querySelector<HTMLButtonElement>('button')!.disabled).toBe(true);
    expect(sent.at(-1)).toEqual({ type: 'QUEUE_VIDEO', language: 'es', videoId: 'vWySIREExjo' });
  });

  it('offer nothing for a video YouTube says is in another language', async () => {
    const sent = load('search.html', { vWySIREExjo: { status: 'other_language', language: 'en' } });
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));

    hover('vWySIREExjo');
    expect(badge('vWySIREExjo')).toBeNull();
    expect(layer().textContent).toBe('');
  });

  it('say so when "+ Add" is refused as another language', async () => {
    const sent = load('search.html', {}, 'other_language');
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));

    hover('vWySIREExjo');
    layer().querySelector<HTMLButtonElement>('button')!.click();
    await vi.waitFor(() => expect(layer().textContent).toBe('Not Spanish'));
    expect(layer().querySelector<HTMLButtonElement>('button')!.disabled).toBe(true);
  });

  it('keep the hover while the inline preview plays over the card', async () => {
    load('home.html', { HmntX1uDjKs: { status: 'scored', percentUnderstood: 80, newWords: 3 } });
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(badge('HmntX1uDjKs')).not.toBeNull());

    hover('HmntX1uDjKs');
    const preview = document.createElement('ytd-video-preview');
    document.body.appendChild(preview);
    preview.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    expect(layer().textContent).toBe('80%· 3 new');
    window.dispatchEvent(new Event('scroll'));
    expect(layer().textContent).toBe('');
  });

  it('redraw every card when the background clears its cache', async () => {
    let percent = 80;
    const sent = load('home.html', {});
    chrome.runtime.sendMessage = vi.fn((message: BackgroundMessage, respond: (r: unknown) => void) => {
      sent.push(message);
      respond({ ok: true, videos: { HmntX1uDjKs: { status: 'scored', percentUnderstood: percent, newWords: 3 } } });
    }) as unknown as typeof chrome.runtime.sendMessage;
    badges = startFitBadges(() => 'es');
    await vi.waitFor(() => expect(badge('HmntX1uDjKs')?.textContent).toBe('80%'));

    percent = 85;
    const [listener] = vi.mocked(chrome.storage.onChanged.addListener).mock.calls.at(-1)!;
    listener({ [FIT_CACHE_KEY]: { oldValue: { clearedAt: 0 }, newValue: { clearedAt: 1 } } }, 'local');
    await vi.waitFor(() => expect(badge('HmntX1uDjKs')?.textContent).toBe('85%'));
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

describe('queuedLabel', () => {
  it('names the learner\'s language when the video is in another', () => {
    expect(queuedLabel('other_language', 'de')).toBe('Not German');
    expect(queuedLabel('pending', 'de')).toBe('Queued');
    expect(queuedLabel('skipped', 'de')).toBe('Unavailable');
  });
});

describe('percentLabel', () => {
  it('never rounds up to everything', () => {
    expect(percentLabel(99.6)).toBe('99%');
    expect(percentLabel(100)).toBe('100%');
  });
});
