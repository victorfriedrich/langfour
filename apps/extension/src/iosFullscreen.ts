// In-page fullscreen for YouTube on iPhone.
//
// Safari on iPhone has no element fullscreen, so YouTube's fullscreen button
// hands the <video> to iOS's native player (webkitEnterFullscreen). That
// player is not part of the page: neither YouTube's captions nor ours can be
// drawn in it. Instead, the native player is left as soon as it starts and
// the page's player is stretched over the whole screen, captions included.
// Turning the phone sideways then gives a fullscreen video with tappable
// captions; Safari hides its own bars in landscape.

const activeClassName = 'lf-fullscreen';
const exitButtonClassName = 'lf-fullscreen-exit';

type WebkitVideo = HTMLVideoElement & {
  webkitExitFullscreen?: () => void;
  webkitDisplayingFullscreen?: boolean;
};

// iOS ignores leaving while its player is still animating in, so keep asking
// until it is gone.
function leaveNativePlayer(video: WebkitVideo, attempt = 0) {
  if (attempt > 0 && !video.webkitDisplayingFullscreen) return;
  video.webkitExitFullscreen?.();
  if (attempt < 10) setTimeout(() => leaveNativePlayer(video, attempt + 1), 150 * (attempt + 1));
}

function playerContainer(): HTMLElement | null {
  return document.querySelector<HTMLElement>('#player-container-id');
}

function relayout() {
  // YouTube sizes the video and its captions from the container on resize.
  window.dispatchEvent(new Event('resize'));
}

// Where the page was scrolled before, to put it back on leaving.
let scrollBefore = 0;

function enter() {
  const container = playerContainer();
  if (!container) return;
  scrollBefore = window.scrollY;
  document.documentElement.classList.add(activeClassName);
  if (!container.querySelector(`.${exitButtonClassName}`)) {
    const exit = document.createElement('button');
    exit.className = exitButtonClassName;
    exit.type = 'button';
    exit.setAttribute('aria-label', 'Exit fullscreen');
    exit.textContent = '×';
    // The player cancels touches inside it, so a click may never come.
    for (const type of ['touchend', 'click']) {
      exit.addEventListener(type, (event) => {
        event.preventDefault();
        event.stopPropagation();
        leave();
      });
    }
    container.appendChild(exit);
  }
  relayout();
  // Scrolling down is what makes Safari collapse its bars.
  setTimeout(() => window.scrollTo(0, window.scrollY + 100), 50);
}

function leave() {
  if (!document.documentElement.classList.contains(activeClassName)) return;
  document.documentElement.classList.remove(activeClassName);
  playerContainer()?.querySelector(`.${exitButtonClassName}`)?.remove();
  relayout();
  window.scrollTo(0, scrollBefore);
}

export function replaceNativeFullscreen() {
  document.addEventListener(
    'webkitbeginfullscreen',
    (event) => {
      const video = event.target as WebkitVideo;
      leaveNativePlayer(video);
      // YouTube's button toggles: a second press leaves our fullscreen.
      if (document.documentElement.classList.contains(activeClassName)) leave();
      else enter();
    },
    { capture: true },
  );
  // A new video (YouTube navigates without reloading) starts inline. The
  // mobile site fires state-navigatestart on window (desktop's
  // yt-navigate-start never comes there).
  window.addEventListener('state-navigatestart', leave);
}
