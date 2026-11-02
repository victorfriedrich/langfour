import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/dom';
import {
  channelIdOf,
  mountChannelPage,
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

function fakeApi(answer: Answer<ChannelView>) {
  const calls: unknown[][] = [];
  const api: ChannelApi = {
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

describe('mountChannelPage', () => {
  it('adds Favourite next to Subscribe and toggles it', async () => {
    channelPage();
    const { api, calls } = fakeApi({ ok: true, value: view({ favourite: true }) });
    await mountChannelPage(document, '/@viajes', 'es', api);

    const button = screen.getByRole('button', { name: 'Favourited' });
    expect(button).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(button);
    await screen.findByRole('button', { name: 'Favourite' });
    expect(calls).toContainEqual(['favourite', CHANNEL, 'es', false]);
    // The view is read again, for the progress line.
    await waitFor(() => expect(calls.filter((c) => c[0] === 'view')).toHaveLength(2));
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
    expect(screen.getByText('13 videos indexed · 9 at your level')).toBeInTheDocument();
    const content = document.querySelector('ytd-two-column-browse-results-renderer') as HTMLElement;
    expect(content.style.display).toBe('none');

    // Home is already YouTube's selected tab, so YouTube won't navigate.
    fireEvent.click(home.firstElementChild!);
    expect(home).toHaveAttribute('aria-selected', 'true');
    expect(home.firstElementChild).toHaveClass('ytTabShapeTabSelected');
    expect(screen.queryByText('13 videos indexed · 9 at your level')).toBeNull();
    expect(content.style.display).toBe('');
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
});
