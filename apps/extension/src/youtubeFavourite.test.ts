import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from 'vitest';
import { mountChannelPage, unmount } from './youtubeChannel';

vi.mock('./api-service', () => ({
  addChannelCoreWords: vi.fn(),
  getChannel: vi.fn(),
  getChannelFavourite: vi.fn(),
  setChannelFavourite: vi.fn(),
}));
vi.mock('./youtubeChannel', async (actual) => ({
  ...(await actual<typeof import('./youtubeChannel')>()),
  mountChannelPage: vi.fn(),
  unmount: vi.fn(),
}));

const CHANNEL = 'UC' + 'a'.repeat(22);

const prefs = (preferredLanguage: string) =>
  document.dispatchEvent(new CustomEvent('prefs', { detail: { preferredLanguage } }));
const navigate = (detail: unknown) =>
  document.dispatchEvent(new CustomEvent('yt-navigate-finish', { detail }));
const navigation = (externalId: string) => ({
  response: { response: { metadata: { channelMetadataRenderer: { externalId } } } },
});

describe('youtubeFavourite', () => {
  let added: MockInstance<typeof document.addEventListener>;

  beforeEach(async () => {
    vi.mocked(mountChannelPage).mockClear();
    vi.mocked(unmount).mockClear();
    vi.stubGlobal('location', { host: 'www.youtube.com', pathname: '/@viajes' });
    vi.resetModules();
    // Each import adds its listeners to the one document; they come off after.
    added = vi.spyOn(document, 'addEventListener');
    await import('./youtubeFavourite');
  });

  afterEach(() => {
    for (const [type, listener] of added.mock.calls) document.removeEventListener(type, listener as EventListener);
    added.mockRestore();
  });

  it('waits for the language, then mounts with no channel to expect', () => {
    expect(mountChannelPage).not.toHaveBeenCalled();
    prefs('es');
    expect(mountChannelPage).toHaveBeenCalledWith(document, '/@viajes', 'es', expect.anything(), null);
  });

  it('takes the channel from the navigation event, on the document', () => {
    prefs('es');
    navigate(navigation(CHANNEL));
    expect(mountChannelPage).toHaveBeenLastCalledWith(document, '/@viajes', 'es', expect.anything(), CHANNEL);
  });

  it('keeps that channel when the language changes on the same page', () => {
    prefs('es');
    navigate(navigation(CHANNEL));
    prefs('de');
    expect(mountChannelPage).toHaveBeenLastCalledWith(document, '/@viajes', 'de', expect.anything(), CHANNEL);
  });

  it('takes everything out without a language', () => {
    prefs('es');
    prefs('nonsense');
    expect(unmount).toHaveBeenCalledWith(document);
  });

  it('does not mount again for the same prefs', () => {
    prefs('es');
    prefs('es');
    expect(mountChannelPage).toHaveBeenCalledTimes(1);
  });
});
