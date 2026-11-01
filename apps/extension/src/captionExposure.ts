import {
  CAPTION_TICK_MS,
  CaptionWords,
  ExposureQueue,
  FLUSH_MS,
  MAX_PLAYBACK_RATE,
  mediaKey,
  tokensOf,
} from './exposure';
import { CaptionExposureEvent } from './types';

type Site = { subtitleSelector: string; videoSelector: string };

/**
 * Samples the captions on screen while the video plays and hands the words
 * the user watched to the content script as `caption-exposure` events. A
 * paused, seeking, sped-up or hidden video counts nothing, and neither do
 * captions turned off, since then there are none on screen.
 */
export function watchCaptions(site: Site): void {
  if (!site.subtitleSelector || !site.videoSelector) return;
  const words = new CaptionWords();
  const queue = new ExposureQueue();
  let media = mediaKey(location.href);

  const flush = () => {
    for (const detail of queue.take()) {
      document.dispatchEvent(new CustomEvent<CaptionExposureEvent>('caption-exposure', { detail }));
    }
  };

  setInterval(() => {
    // YouTube changes videos without loading a page.
    const current = mediaKey(location.href);
    if (current !== media) {
      flush();
      words.reset();
      media = current;
    }

    const video = document.querySelector<HTMLVideoElement>(site.videoSelector);
    const captions = document.querySelector<HTMLElement>(site.subtitleSelector);
    const watching =
      video && !video.paused && !video.ended && !video.seeking &&
      video.playbackRate <= MAX_PLAYBACK_RATE && document.visibilityState === 'visible';
    if (!watching || !captions) {
      words.interrupt();
      return;
    }
    queue.add(media, words.sample(tokensOf(captions.innerText)));
  }, CAPTION_TICK_MS);

  setInterval(flush, FLUSH_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
  window.addEventListener('pagehide', flush);
}
