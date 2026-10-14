import { afterEach, describe, expect, it, vi } from 'vitest';
import { askBackground } from './messages';

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
