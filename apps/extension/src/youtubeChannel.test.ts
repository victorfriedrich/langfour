import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/dom';
import {
  channelIdOf,
  mountChannelPage,
  navigatedChannelId,
  renderPanel,
  summaryText,
  unmount,
  type Answer,
  type ChannelApi,
  type ChannelView,
} from './youtubeChannel';

const CHANNEL = 'UC' + 'a'.repeat(22);

const view = (over: Partial<ChannelView> = {}): ChannelView => ({
  favourite: false, uploads: null, added: 13, videos: 13, at_level: 9, understood: 86.6, best: [], progress: null,
  core_words: null, ...over,
});

const words = (n: number) => Array.from({ length: n }, (_, i) => ({ word_id: i, word: `palabra${i}` }));

// The parts of a YouTube channel page this touches, as of 2026-11.
function channelPage(): void {
  document.body.innerHTML = `
    <ytd-browse page-subtype="channels">
      <yt-flexible-actions-view-model>
        <div class="ytFlexibleActionsViewModelAction"><button>Subscribe</button></div>
      </yt-flexible-actions-view-model>
      <yt-tab-group-shape><div class="tabGroupShapeTabs" role="tablist">
        <div role="tab" class="ytTabShapeHost" aria-selected="true">
          <div class="ytTabShapeTab ytTabShapeTabSelected">Home</div><div class="ytTabShapeTabBar ytTabShapeTabBarSelected"></div>
        </div>
        <div role="tab" class="ytTabShapeHost" aria-selected="false">
          <div class="ytTabShapeTab">Videos</div><div class="ytTabShapeTabBar"></div>
        </div>
        <div class="ytTabShapeHost ytTabShapeLastTab">Search</div>
      </div></yt-tab-group-shape>
      <ytd-two-column-browse-results-renderer>YouTube's videos</ytd-two-column-browse-results-renderer>
    </ytd-browse>`;
  const browse = document.querySelector('ytd-browse') as Element & { data?: unknown };
  browse.data = { metadata: { channelMetadataRenderer: { externalId: CHANNEL } } };
}

function fakeApi(answer: Answer<ChannelView>, favourited = false) {
  const calls: unknown[][] = [];
  const api: ChannelApi = {
    favourited: vi.fn(async (...args) => {
      calls.push(['favourited', ...args]);
      return { ok: true as const, value: { favourite: favourited } };
    }),
    view: vi.fn(async (...args) => { calls.push(['view', ...args]); return answer; }),
    favourite: vi.fn(async (...args) => {
      calls.push(['favourite', ...args]);
      return { ok: true as const, value: { favourite: args[2] } };
    }),
    addCoreWords: vi.fn(async (...args) => {
      calls.push(['add', ...args]);
      return { ok: true as const, value: { added: ['palabra0'] } };
    }),
    signIn: vi.fn(),
  };
  return { api, calls };
}

afterEach(() => unmount(document));

describe('summaryText', () => {
  const favourite = (over: Partial<ChannelView>) => view({ favourite: true, uploads: 'queued', ...over });
  const none = { videos: 0, at_level: 0, added: 0, understood: null };

  it('counts videos added while a favourite is being indexed', () => {
    expect(summaryText(favourite({ progress: { added: 34, total: 212 } }), 'es')).toBe('34 of 212 videos added · 86.6% understood · 9 at your level');
  });

  it('drops the total once the channel stalls', () => {
    expect(summaryText(favourite({ progress: { added: 34, total: null } }), 'es')).toBe('34 videos added · 86.6% understood · 9 at your level');
  });

  it('says what is indexed otherwise, and how to get more', () => {
    expect(summaryText(view(), 'es')).toBe('13 videos indexed · 86.6% understood · 9 at your level');
    expect(summaryText(favourite({}), 'es')).toBe('13 videos indexed · 86.6% understood · 9 at your level');
    expect(summaryText(view(none), 'es')).toBe('No videos from this channel are indexed yet. Favourite it to add them.');
  });

  it('says why a favourite is adding nothing', () => {
    expect(summaryText(favourite({ ...none, uploads: 'other_language' }), 'de')).toBe(
      'This channel doesn\'t seem to be in German, so its videos won\'t be added.');
    expect(summaryText(favourite({ ...none, uploads: 'pending' }), 'es')).toBe('This channel\'s videos can\'t be added right now.');
    expect(summaryText(favourite({ uploads: 'pending' }), 'es')).toBe(
      '13 videos indexed · 86.6% understood · 9 at your level · More can\'t be added right now');
    expect(summaryText(favourite(none), 'es')).toBe('None of this channel\'s videos could be added.');
  });

  it('gives a new favourite a moment before saying so', () => {
    expect(summaryText(favourite({ ...none, uploads: 'pending' }), 'es', true)).toBe('Looking for this channel\'s videos…');
    expect(summaryText(favourite({ uploads: 'pending' }), 'es', true)).toBe('13 videos indexed · 86.6% understood · 9 at your level');
  });

  it('counts videos finished but not loaded yet', () => {
    expect(summaryText(favourite({ videos: 0, at_level: 0, added: 4, understood: null }), 'es')).toBe('4 videos added');
  });
});

describe('channelIdOf', () => {
  it('reads a @handle page\'s id from YouTube\'s data', () => {
    channelPage();
    expect(channelIdOf(document, '/@viajes')).toBe(CHANNEL);
  });

  it('falls back to a /channel/ path, and never returns a handle', () => {
    document.body.innerHTML = '';
    expect(channelIdOf(document, `/channel/${CHANNEL}/videos`)).toBe(CHANNEL);
    expect(channelIdOf(document, '/@viajes')).toBeNull();
  });
});

describe('renderPanel', () => {
  it('shows fifteen core words, the rest behind a chip, and adds them', async () => {
    const add = vi.fn(async () => true);
    const core = { words: words(25), before: 86.6, after: 95.5 };
    document.body.append(renderPanel(document, { ok: true, value: view({ core_words: core }) }, (v) => summaryText(v, 'es'), add, vi.fn()));

    expect(screen.getByText('Top words you don\'t know yet')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toHaveLength(16);
    fireEvent.click(screen.getByText('+ 10 more'));
    expect(screen.getAllByRole('listitem')).toHaveLength(25);
    expect(screen.getByText('86.6% → 95.5% understood')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Add 25 to my reviews'));
    await screen.findByText('Added to your reviews');
    expect(add).toHaveBeenCalledOnce();
  });

  it('lets a failed add be tried again', async () => {
    const core = { words: words(2), before: 80, after: 84 };
    document.body.append(renderPanel(document, { ok: true, value: view({ core_words: core }) }, (v) => summaryText(v, 'es'), async () => false, vi.fn()));
    fireEvent.click(screen.getByText('Add 2 to my reviews'));
    const retry = await screen.findByText('Could not add them. Try again');
    expect(retry).not.toBeDisabled();
  });

  it('links the videos easiest for the learner, most understood first', () => {
    const best = [{ video_id: 'abc', title: 'Construyo un búnker', understood: 89.8 }, { video_id: 'def', title: 'Pesco en el lago', understood: 88.7 }];
    document.body.append(renderPanel(document, { ok: true, value: view({ best }) }, (v) => summaryText(v, 'es'), vi.fn(), vi.fn()));
    expect(screen.getByText('Easiest for you')).toBeInTheDocument();
    const links = screen.getAllByRole('link');
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Construyo un búnker', '/watch?v=abc'], ['Pesco en el lago', '/watch?v=def']]);
    expect(screen.getByText('89.8% understood')).toBeInTheDocument();
  });

  it('leaves the videos card out for a channel with none indexed', () => {
    document.body.append(renderPanel(document, { ok: true, value: view({ videos: 0 }) }, (v) => summaryText(v, 'es'), vi.fn(), vi.fn()));
    expect(screen.queryByText('Easiest for you')).toBeNull();
  });

  it('asks a signed-out viewer to sign in', () => {
    const signIn = vi.fn();
    document.body.append(renderPanel(document, { ok: false, signedOut: true }, (v) => summaryText(v, 'es'), vi.fn(), signIn));
    fireEvent.click(screen.getByText('Sign in'));
    expect(signIn).toHaveBeenCalledOnce();
  });
});

describe('navigatedChannelId', () => {
  it('reads the channel from the navigation, as the page still has the old one', () => {
    const other = 'UC' + 'b'.repeat(22);
    expect(navigatedChannelId({ response: { response: { metadata: { channelMetadataRenderer: { externalId: other } } } } })).toBe(other);
    expect(navigatedChannelId({ endpoint: { browseEndpoint: { browseId: other } } })).toBe(other);
  });

  it('has no channel for other pages', () => {
    expect(navigatedChannelId({ endpoint: { browseEndpoint: { browseId: 'FEwhat_to_watch' } } })).toBeNull();
    expect(navigatedChannelId(undefined)).toBeNull();
  });
});

describe('mountChannelPage', () => {
  it('adds Favourite next to Subscribe and toggles it', async () => {
    channelPage();
    const { api, calls } = fakeApi({ ok: true, value: view() }, true);
    await mountChannelPage(document, '/@viajes', 'es', api);

    const button = screen.getByRole('button', { name: 'Favourited' });
    expect(button).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(button);
    await screen.findByRole('button', { name: 'Favourite' });
    expect(calls).toContainEqual(['favourite', CHANNEL, 'es', false]);
  });

  it('reads only the favourite until the tab opens', async () => {
    channelPage();
    const { api, calls } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);
    expect(calls).toEqual([['favourited', CHANNEL]]);

    fireEvent.click(screen.getByRole('tab', { name: 'Langfour' }));
    await screen.findByText('13 videos indexed · 86.6% understood · 9 at your level');
    expect(calls).toContainEqual(['view', CHANNEL, 'es']);
  });

  it('waits for the data of the channel navigated to', async () => {
    channelPage();
    const next = 'UC' + 'b'.repeat(22);
    const { api, calls } = fakeApi({ ok: true, value: view() });
    const mounting = mountChannelPage(document, '/@other', 'es', api, next);
    await new Promise((r) => setTimeout(r, 150));
    expect(calls).toEqual([]);

    const browse = document.querySelector('ytd-browse') as Element & { data?: unknown };
    browse.data = { metadata: { channelMetadataRenderer: { externalId: next } } };
    await mounting;
    expect(calls).toEqual([['favourited', next]]);
  });

  it('gives up on a page the next navigation replaced', async () => {
    channelPage();
    const { api, calls } = fakeApi({ ok: true, value: view() });
    const stale = mountChannelPage(document, '/@other', 'es', api, 'UC' + 'b'.repeat(22));
    await mountChannelPage(document, '/@viajes', 'es', api, CHANNEL);
    await stale;
    expect(calls).toEqual([['favourited', CHANNEL]]);
    expect(document.querySelectorAll('.lf-fav')).toHaveLength(1);
  });

  it('opens the Langfour tab in place of YouTube\'s content, and gives it back', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);

    const tab = screen.getByRole('tab', { name: 'Langfour' });
    expect(tab.nextElementSibling).toHaveClass('ytTabShapeLastTab');
    fireEvent.click(tab);
    expect(tab).toHaveAttribute('aria-selected', 'true');
    const home = screen.getByRole('tab', { name: 'Home' });
    expect(home).toHaveAttribute('aria-selected', 'false');
    await screen.findByText('13 videos indexed · 86.6% understood · 9 at your level');
    const content = document.querySelector('ytd-two-column-browse-results-renderer') as HTMLElement;
    expect(content.style.display).toBe('none');

    // Home is already YouTube's selected tab, so YouTube won't navigate.
    fireEvent.click(home.firstElementChild!);
    expect(home).toHaveAttribute('aria-selected', 'true');
    expect(home.firstElementChild).toHaveClass('ytTabShapeTabSelected');
    expect(screen.queryByText('13 videos indexed · 86.6% understood · 9 at your level')).toBeNull();
    expect(content.style.display).toBe('');
  });

  it('lines the panel up with the tab bar rather than YouTube\'s centred column', async () => {
    channelPage();
    const bar = document.createElement('tp-yt-paper-tabs');
    document.querySelector('ytd-browse')!.append(bar);
    const rect = (left: number, width: number) => ({ left, width }) as DOMRect;
    vi.spyOn(bar, 'getBoundingClientRect').mockReturnValue(rect(141, 1070));
    vi.spyOn(document.querySelector('ytd-browse')!, 'getBoundingClientRect').mockReturnValue(rect(72, 1208));
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);

    fireEvent.click(screen.getByRole('tab', { name: 'Langfour' }));
    const panel = await screen.findByRole('tabpanel');
    expect(panel.style.marginLeft).toBe('69px');
    expect(panel.style.width).toBe('1070px');
  });

  it('shows YouTube\'s content again even if the page changed underneath', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);
    fireEvent.click(screen.getByRole('tab', { name: 'Langfour' }));
    const content = document.querySelector('ytd-two-column-browse-results-renderer') as HTMLElement;
    document.querySelector('ytd-browse')!.setAttribute('page-subtype', 'home');

    unmount(document);
    expect(content.style.display).toBe('');
  });

  it('adds the tab without waiting for the favourite read', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() }, true);
    let answer: (value: Answer<{ favourite: boolean }>) => void = () => {};
    vi.mocked(api.favourited).mockReturnValue(new Promise((resolve) => { answer = resolve; }));

    const mounting = mountChannelPage(document, '/@viajes', 'es', api);
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Langfour' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Favourite/ })).toBeNull();

    answer({ ok: true, value: { favourite: true } });
    await mounting;
    expect(screen.getByRole('button', { name: 'Favourited' })).toBeInTheDocument();
  });

  it('puts the button and tab back when YouTube rebuilds its header', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() }, true);
    await mountChannelPage(document, '/@viajes', 'es', api);

    document.querySelector('yt-flexible-actions-view-model')!.innerHTML = '<div><button>Subscribe</button></div>';
    await waitFor(() => expect(screen.getByRole('button', { name: 'Favourited' })).toBeInTheDocument());

    const bar = document.querySelector('.tabGroupShapeTabs')!;
    bar.querySelector('[data-langfour-channel="tab"]')!.remove();
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Langfour' })).toBeInTheDocument());
  });

  it('moves the tab back to the end when YouTube re-renders its tabs past it', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);
    const bar = document.querySelector('.tabGroupShapeTabs')!;
    const tab = screen.getByRole('tab', { name: 'Langfour' });

    bar.prepend(tab);
    await waitFor(() => expect(tab.nextElementSibling).toHaveClass('ytTabShapeLastTab'));
    expect(screen.getAllByRole('tab').map((t) => t.textContent!.trim())).toEqual(['Home', 'Videos', 'Langfour']);
  });

  it('adds the button once YouTube renders its header', async () => {
    channelPage();
    const actions = document.querySelector('yt-flexible-actions-view-model')!;
    actions.remove();
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);
    expect(screen.queryByRole('button', { name: 'Favourite' })).toBeNull();

    document.querySelector('ytd-browse')!.prepend(actions);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Favourite' })).toBeInTheDocument());
  });

  it('takes everything out again on the next navigation', async () => {
    channelPage();
    const { api } = fakeApi({ ok: true, value: view() });
    await mountChannelPage(document, '/@viajes', 'es', api);
    fireEvent.click(screen.getByRole('tab', { name: 'Langfour' }));

    await mountChannelPage(document, '/watch', 'es', api);
    expect(document.querySelectorAll('[data-langfour-channel]')).toHaveLength(0);
    expect((document.querySelector('ytd-two-column-browse-results-renderer') as HTMLElement).style.display).toBe('');
  });

  describe('while the tab is open', () => {
    const adding = (added: number) => view({ favourite: true, progress: { added, total: 15 } });
    const home = () => screen.getByRole('tab', { name: 'Home' }).firstElementChild!;

    async function openTab(api: ChannelApi) {
      vi.useFakeTimers();
      channelPage();
      await mountChannelPage(document, '/@viajes', 'es', api);
      fireEvent.click(screen.getByRole('tab', { name: 'Langfour' }));
      await vi.advanceTimersByTimeAsync(0);
    }

    afterEach(() => vi.useRealTimers());

    it('updates the line each minute while videos arrive, and stops when closed', async () => {
      const { api } = fakeApi({ ok: true, value: adding(13) });
      await openTab(api);
      expect(screen.getByText('13 of 15 videos added · 86.6% understood · 9 at your level')).toBeInTheDocument();

      vi.mocked(api.view).mockResolvedValue({ ok: true, value: adding(14) });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByText('14 of 15 videos added · 86.6% understood · 9 at your level')).toBeInTheDocument();

      const calls = vi.mocked(api.view).mock.calls.length;
      fireEvent.click(home());
      await vi.advanceTimersByTimeAsync(180_000);
      expect(vi.mocked(api.view).mock.calls.length).toBe(calls);
    });

    it('looks again soon after a favourite, while its uploads are listed', async () => {
      const { api } = fakeApi({ ok: true, value: view() });
      await openTab(api);
      expect(api.view).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole('button', { name: 'Favourite' }));
      await vi.advanceTimersByTimeAsync(0);
      expect(api.view).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(api.view).toHaveBeenCalledTimes(3);

      const calls = vi.mocked(api.view).mock.calls.length;
      await vi.advanceTimersByTimeAsync(20_000);
      const settled = vi.mocked(api.view).mock.calls.length;
      expect(settled).toBeGreaterThan(calls);
      await vi.advanceTimersByTimeAsync(180_000);
      expect(vi.mocked(api.view).mock.calls.length).toBe(settled);
    });

    it('keeps what is showing when a refresh fails, and tries again', async () => {
      const core = { words: words(25), before: 80, after: 90 };
      const { api } = fakeApi({ ok: true, value: view({ core_words: core, progress: { added: 1, total: 2 } }) });
      await openTab(api);
      fireEvent.click(screen.getByText('+ 10 more'));

      vi.mocked(api.view).mockResolvedValue({ ok: false, signedOut: false });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByText('1 of 2 videos added · 86.6% understood · 9 at your level')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(25);

      // A new easiest video shows; the words stay unfolded.
      const best = [{ video_id: 'abc', title: 'Construyo un búnker', understood: 89.8 }];
      vi.mocked(api.view).mockResolvedValue({ ok: true, value: view({ core_words: core, best, progress: { added: 2, total: 2 } }) });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByText('2 of 2 videos added · 86.6% understood · 9 at your level')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Construyo un búnker' })).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(26);
    });

    it('stops looking once a channel has stalled', async () => {
      const { api } = fakeApi({ ok: true, value: view({ progress: { added: 3, total: null } }) });
      await openTab(api);
      await vi.advanceTimersByTimeAsync(300_000);
      expect(api.view).toHaveBeenCalledTimes(1);
    });

    it('waits while the browser tab is hidden and catches up when it is shown', async () => {
      const { api } = fakeApi({ ok: true, value: adding(13) });
      await openTab(api);
      const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
      await vi.advanceTimersByTimeAsync(300_000);
      expect(api.view).toHaveBeenCalledTimes(1);

      hidden.mockReturnValue(false);
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
      expect(api.view).toHaveBeenCalledTimes(2);
      hidden.mockRestore();
    });

    it('stays the selected tab when YouTube rebuilds the tab bar', async () => {
      const { api } = fakeApi({ ok: true, value: view() });
      await openTab(api);
      vi.useRealTimers();
      const bar = document.querySelector('.tabGroupShapeTabs')!;
      const home = screen.getByRole('tab', { name: 'Home' });
      const rebuilt = home.cloneNode(true) as HTMLElement;
      rebuilt.setAttribute('aria-selected', 'true');
      home.replaceWith(rebuilt);

      await waitFor(() => expect(rebuilt).toHaveAttribute('aria-selected', 'false'));
      expect(screen.getByRole('tab', { name: 'Langfour' })).toHaveAttribute('aria-selected', 'true');
      expect(bar.querySelectorAll('[aria-selected="true"]')).toHaveLength(1);

      // Closing gives the selection to the tab that's there now.
      fireEvent.click(rebuilt.firstElementChild!);
      expect(rebuilt).toHaveAttribute('aria-selected', 'true');
    });

    it('keeps the card as it is on a refresh, and after its words are added', async () => {
      const core = { words: words(25), before: 80, after: 90 };
      const { api } = fakeApi({ ok: true, value: view({ core_words: core, progress: { added: 1, total: 2 } }) });
      await openTab(api);
      fireEvent.click(screen.getByText('+ 10 more'));
      fireEvent.click(screen.getByText('Add 25 to my reviews'));
      await vi.advanceTimersByTimeAsync(0);
      expect(screen.getByText('Added to your reviews')).toBeInTheDocument();

      // The server stops offering a card once its words are added.
      vi.mocked(api.view).mockResolvedValue({ ok: true, value: view({ core_words: null, progress: { added: 2, total: 3 } }) });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByText('2 of 3 videos added · 86.6% understood · 9 at your level')).toBeInTheDocument();
      expect(screen.getByText('Added to your reviews')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(25);
    });
  });
});
