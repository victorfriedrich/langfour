interface SubtitleApi {
  subtitleSelector: string;
  // The playing video, to tell whether captions on screen are being watched.
  videoSelector: string;
  subtitlePopupSelector: string;
  pause: () => boolean;
  play: () => void;
}

interface SubtitleApiWithReplace extends SubtitleApi {
  subtitleTransformType: 'replace';
}

interface SubtitleApiWithMask extends SubtitleApi {
  subtitleTransformType: 'mask';
  maskContainerSelector: string;
}

const youtube = {
  subtitleTransformType: 'replace',
  subtitleSelector: '#movie_player .ytp-caption-window-container',
  videoSelector: '#movie_player video',
  subtitlePopupSelector: '#movie_player',
  pause() {
    if (document.querySelector<HTMLVideoElement>('#movie_player video')?.paused)
      return false;
    document.querySelector<HTMLVideoElement>('#movie_player video')?.pause();
    return true;
  },
  play() {
    document.querySelector<HTMLVideoElement>('#movie_player video')?.play();
  },
} satisfies SubtitleApiWithReplace;

const siteApiMap = {
  'www.netflix.com': {
    subtitleTransformType: 'replace',
    subtitleSelector: '.player-timedtext:not(.billboard .player-timedtext)',
    videoSelector: '.watch-video video',
    subtitlePopupSelector: '.watch-video',
    pause() {
      if (
        document.querySelector<HTMLButtonElement>('[data-uia^="control-play-pause-play"]')
      )
        return false;
      document
        .querySelector<HTMLButtonElement>('[data-uia^="control-play-pause-pause"]')
        ?.click();
      return true;
    },
    play() {
      document
        .querySelector<HTMLButtonElement>('[data-uia^="control-play-pause-play"]')
        ?.click();
    },
  },
  'www.youtube.com': youtube,
  // The mobile site (Safari on iPhone) uses the same player and caption markup.
  'm.youtube.com': youtube,
  'www.primevideo.com': {
    subtitleTransformType: 'mask',
    subtitleSelector: '.atvwebplayersdk-captions-overlay',
    videoSelector: '#dv-web-player video',
    maskContainerSelector: '.atvwebplayersdk-captions-text',
    subtitlePopupSelector: '.atvwebplayersdk-overlays-container',
    pause() {
      if (document.querySelector<HTMLVideoElement>('#dv-web-player video')?.paused)
        return false;
      document.querySelector<HTMLVideoElement>('#dv-web-player video')?.pause();
      return true;
    },
    play() {
      document.querySelector<HTMLVideoElement>('#dv-web-player video')?.play();
    },
  },
} satisfies Record<string, SubtitleApiWithReplace | SubtitleApiWithMask>;

type Host = keyof typeof siteApiMap;

export function isAllowedHost(host: string): host is Host {
  return host in siteApiMap;
}
export function getSiteSpecificApi(
  host: string,
): SubtitleApiWithReplace | SubtitleApiWithMask {
  if (isAllowedHost(host)) return siteApiMap[host];
  return {
    subtitleTransformType: 'replace',
    subtitleSelector: '',
    videoSelector: '',
    subtitlePopupSelector: '',
    pause: () => false,
    play: () => undefined,
  };
}
