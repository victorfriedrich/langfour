import { bookmarkChannel, checkChannelBookmarked } from './api-service';

(() => {
  if (!location.host.includes('youtube.com')) return;

  // detect standard channel URLs including /channel/UC..., @handles and legacy /c/
  // or /user/ routes
  const isChannelPage = () =>
    /^\/(channel\/|@|c\/|user\/)/.test(location.pathname);

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const waitEl = async (sel: string, t = 10000): Promise<Element | null> => {
    const s = Date.now();
    while (Date.now() - s < t) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(250);
    }
    throw new Error(`Timeout: ${sel} not found`);
  };

  const createBookmarkIcon = (filled: boolean) => {
    const namespace = 'http://www.w3.org/2000/svg';
    const icon = document.createElementNS(namespace, 'svg');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('width', '16');
    icon.setAttribute('height', '16');
    icon.setAttribute('aria-hidden', 'true');

    const path = document.createElementNS(namespace, 'path');
    path.setAttribute(
      'd',
      filled
        ? 'M6 3h12a1 1 0 0 1 1 1v17l-7-3-7 3V4a1 1 0 0 1 1-1z'
        : 'M6 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v17l-7-3-7 3V4z',
    );
    path.setAttribute('fill', filled ? 'currentColor' : 'none');
    if (!filled) {
      path.setAttribute('stroke', 'currentColor');
      path.setAttribute('stroke-width', '2');
    }
    icon.appendChild(path);
    return icon;
  };

  const showBookmarkState = (
    button: HTMLButtonElement,
    label: string,
    filled = false,
  ) => {
    button.replaceChildren(createBookmarkIcon(filled), document.createTextNode(label));
  };

  if (!document.getElementById('yt-bookmark-style')) {
    const css =
      '.yt-bookmark-btn{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;font-weight:500;font-size:14px;border-radius:18px;cursor:pointer;border:1px solid var(--yt-spec-10-percent-layer,#ccc);background:#fff;color:#0f0f0f;transition:background .2s,border-color .2s,opacity .2s;}' +
      '.yt-bookmark-btn[data-stage="queued"]{pointer-events:none;opacity:.7;}' +
      '.yt-bookmark-btn[data-stage="done"]{background:#1f1f1f;border-color:#1f1f1f;color:#fff;}' +
      '.yt-bookmark-spinner{width:12px;height:12px;border-radius:50%;border:2px solid transparent;border-top-color:currentColor;animation:ytSpin .8s linear infinite;}' +
      '@keyframes ytSpin{to{transform:rotate(360deg)}}';
    const style = Object.assign(document.createElement('style'), {
      id: 'yt-bookmark-style',
      textContent: css,
    });
    document.head.appendChild(style);
  }

  async function getChannelId(): Promise<string | null> {
    const p = location.pathname;
    if (p.startsWith('/channel/')) return p.split('/')[2];
    if (p.startsWith('/@')) return p.substring(1).split('/')[0];
    if (p.startsWith('/c/') || p.startsWith('/user/')) {
      const canon = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
      if (canon) {
        const url = new URL(canon.href);
        const m = url.pathname.match(/\/channel\/(.+)/);
        if (m) return m[1];
      }
      const meta = document.querySelector('meta[itemprop="channelId"]');
      if (meta) return meta.getAttribute('content');
    }
    return null;
  }

  async function addButton(): Promise<void> {
    if (!isChannelPage()) return;
    const channelId = await getChannelId();
    if (!channelId) return;

    const subBtn = await waitEl(
      'yt-subscribe-button-view-model button, ytd-subscribe-button-renderer button'
    ).catch(() => null) as HTMLElement | null;
    if (!subBtn) return;
    const subAction =
      subBtn.closest('.yt-flexible-actions-view-model-wiz__action') ||
      subBtn.parentElement;
    const actionWrap = document.createElement('div');
    actionWrap.className = 'yt-flexible-actions-view-model-wiz__action';
    subAction!.after(actionWrap);

    const btn = document.createElement('button');
    btn.className = 'yt-bookmark-btn';
    btn.dataset.stage = 'idle';
    showBookmarkState(btn, ' Bookmark');
    actionWrap.appendChild(btn);

    btn.addEventListener('click', async () => {
      btn.dataset.stage = 'queued';
      const spinner = document.createElement('span');
      spinner.className = 'yt-bookmark-spinner';
      btn.replaceChildren(spinner, document.createTextNode(' Indexing\u00a0Queued'));
      try {
        await bookmarkChannel(channelId);
      } catch (e) {
        console.error('Bookmark error', e);
      }
    });

    try {
      const res = await checkChannelBookmarked(channelId);
      if (res && res.saved) {
        btn.dataset.stage = 'done';
        showBookmarkState(btn, ' Saved', true);
      }
    } catch (e) {
      console.warn('Bookmark check failed', e);
    }
  }

  const run = () => {
    if (isChannelPage()) addButton();
  };

  run();
  window.addEventListener('yt-navigate-finish', run);
})();
