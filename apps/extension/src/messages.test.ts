import { afterEach, describe, expect, it, vi } from 'vitest';
import { askBackground, mayRelay } from './messages';

const message = { type: 'WORD_PROGRESS', wordId: 1 } as const;

/** Each call to sendMessage answers with the next entry; 'silent' never answers. */
function answerWith(...answers: unknown[]) {
  const send = vi.fn((_message: unknown, callback: (response: unknown) => void) => {
    const answer = answers.shift();
    if (answer !== 'silent') callback(answer);
  });
  vi.spyOn(chrome.runtime, 'sendMessage').mockImplementation(send as never);
  return send;
}

afterEach(() => {
  vi.useRealTimers();
});

describe('askBackground', () => {
  it('returns the first answer', async () => {
    const send = answerWith({ ok: true });
    await expect(askBackground(message)).resolves.toEqual({ ok: true });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('asks again after an empty answer', async () => {
    vi.useFakeTimers();
    const send = answerWith(undefined, { ok: true });
    const result = askBackground(message);
    await vi.runAllTimersAsync();
    await expect(result).resolves.toEqual({ ok: true });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('asks again after no answer at all', async () => {
    vi.useFakeTimers();
    const send = answerWith('silent', { ok: true });
    const result = askBackground(message, { timeoutMs: 1000 });
    await vi.runAllTimersAsync();
    await expect(result).resolves.toEqual({ ok: true });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('gives up after the last attempt', async () => {
    vi.useFakeTimers();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const send = answerWith(undefined, 'silent', undefined);
    const result = askBackground(message, { timeoutMs: 1000 });
    await vi.runAllTimersAsync();
    await expect(result).resolves.toBeUndefined();
    expect(send).toHaveBeenCalledTimes(3);
  });
});

describe('mayRelay', () => {
  const favourite = `/api/channels/UC${'a'.repeat(22)}/favourite`;

  it('lets any page look up a word', () => {
    expect(mayRelay('/api/translate-word', 'www.netflix.com')).toBe(true);
  });

  it('keeps the channel endpoints to YouTube', () => {
    expect(mayRelay(favourite, 'www.youtube.com')).toBe(true);
    expect(mayRelay(favourite, 'www.netflix.com')).toBe(false);
    expect(mayRelay(favourite, 'evil.example')).toBe(false);
  });

  it('refuses everything else, on YouTube too', () => {
    expect(mayRelay('/parse', 'www.youtube.com')).toBe(false);
    expect(mayRelay('/api/channels/@handle/favourite', 'www.youtube.com')).toBe(false);
    expect(mayRelay(`/api/channels/UC${'a'.repeat(22)}?language=xx`, 'www.youtube.com')).toBe(false);
  });
});
