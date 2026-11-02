import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readHistory } from './watchBackground';

const page = (account: string) => `<html><script>ytcfg.set({"LOGGED_IN":true,"DATASYNC_ID":"${account}","HL":"en"});</script></html>`;
const local = () => (chrome.storage.local as unknown as { __store: Map<string, unknown> }).__store;

describe('readHistory', () => {
  const backend = vi.fn();

  beforeEach(() => {
    backend.mockReset();
    (chrome.storage.sync as unknown as { __store: Map<string, unknown> }).__store.set('preferredLanguage', 'es');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(page('b||'))));
  });

  it('reads nothing without a yes', async () => {
    expect(await readHistory(backend)).toEqual({ error: 'Not turned on' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('asks about another account, and sends none of its page', async () => {
    local().set('historyConsent', ['a||']);
    expect(await readHistory(backend)).toEqual({ error: 'Another Google account is signed in' });
    expect(local().get('historyNewAccount')).toBe('b||');
    expect(backend).not.toHaveBeenCalled();
  });

  it('does not ask again about an account that said not now', async () => {
    local().set('historyConsent', ['a||']);
    local().set('historyDeclinedAccounts', ['b||']);
    await readHistory(backend);
    expect(local().has('historyNewAccount')).toBe(false);
  });

  it('takes the yes for the account signed in', async () => {
    local().set('historyDeclinedAccounts', ['b||']);
    expect(await readHistory(backend, true)).toEqual({ kept: 0 });
    expect(local().get('historyConsent')).toEqual(['b||']);
    expect(local().get('historyNewAccount')).toBe(false);
  });
});
