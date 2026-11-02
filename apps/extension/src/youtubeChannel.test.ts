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
  favourite: false, videos: 13, at_level: 9, progress: null, core_words: null, ...over,
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
  it('counts videos added while a favourite is being indexed', () => {
    expect(summaryText(view({ progress: { added: 34, total: 212 } }))).toBe('34 of 212 videos added · 9 at your level');
  });

  it('drops the total once the channel stalls', () => {
    expect(summaryText(view({ progress: { added: 34, total: null } }))).toBe('34 videos added · 9 at your level');
  });

  it('says what is indexed otherwise, and how to get more', () => {
    expect(summaryText(view())).toBe('13 videos indexed · 9 at your level');
    expect(summaryText(view({ videos: 0, at_level: 0 }))).toBe(
      'No videos from this channel are indexed yet. Favourite it to add them.');
    expect(summaryText(view({ videos: 0, favourite: true }))).toBe('No videos from this channel are indexed yet.');
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
    document.body.append(renderPanel(document, { ok: true, value: view({ core_words: core }) }, add, vi.fn()));

    expect(screen.getByText('25 core words you don\'t know yet')).toBeInTheDocument();
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
    document.body.append(renderPanel(document, { ok: true, value: view({ core_words: core }) }, async () => false, vi.fn()));
    fireEvent.click(screen.getByText('Add 2 to my reviews'));
    const retry = await screen.findByText('Could not add them. Try again');
    expect(retry).not.toBeDisabled();
  });

  it('asks a signed-out viewer to sign in', () => {
    const signIn = vi.fn();
    document.body.append(renderPanel(document, { ok: false, signedOut: true }, vi.fn(), signIn));
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
    await screen.findByText('13 videos indexed · 9 at your level');
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
    await screen.findByText('13 videos indexed · 9 at your level');
    const content = document.querySelector('ytd-two-column-browse-results-renderer') as HTMLElement;
    expect(content.style.display).toBe('none');

    // Home is already YouTube's selected tab, so YouTube won't navigate.
    fireEvent.click(home.firstElementChild!);
    expect(home).toHaveAttribute('aria-selected', 'true');
    expect(home.firstElementChild).toHaveClass('ytTabShapeTabSelected');
    expect(screen.queryByText('13 videos indexed · 9 at your level')).toBeNull();
    expect(content.style.display).toBe('');
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
      expect(screen.getByText('13 of 15 videos added · 9 at your level')).toBeInTheDocument();

      vi.mocked(api.view).mockResolvedValue({ ok: true, value: adding(14) });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByText('14 of 15 videos added · 9 at your level')).toBeInTheDocument();

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
      expect(screen.getByText('2 of 3 videos added · 9 at your level')).toBeInTheDocument();
      expect(screen.getByText('Added to your reviews')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(25);
    });
  });
});
