import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';
import type { BackgroundMessage, WordStatus } from './messages';

vi.mock('./api-service', () => ({
  fetchTranslation: vi.fn(async () => ({ id: 10, root: 'sacar', translation: 'take out' })),
  translateSection: vi.fn(),
}));

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('checks persistence after an unanswered save and allows a failed save to be retried', async () => {
  vi.useFakeTimers();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const html = readFileSync(join(__dirname, 'reader.html'), 'utf8');
  document.body.innerHTML = html.match(/<body>([\s\S]*)<\/body>/)![1].replace(/<script[\s\S]*?<\/script>/g, '');
  await chrome.storage.local.set({
    currentArticle: { title: 'Example', content: '<p>sacaran</p>' },
    supabaseSession: { access_token: 'test' },
  });
  await chrome.storage.sync.set({ preferredLanguage: 'es', preferredLanguageResolved: true });
  let progressStatus: WordStatus = 'new';
  const send = vi.fn((message: BackgroundMessage, callback: (value: unknown) => void) => {
    if (message.type === 'GET_ACCOUNT') return callback({ account: null });
    if (message.type === 'CLASSIFY_WORDS') return callback({ ok: true, words: [{ token: 'sacaran', word_id: 10, status: 'new' }] });
    if (message.type === 'ADD_WORD_TO_USERWORDS') return callback(undefined);
    if (message.type === 'WORD_PROGRESS') return callback({ ok: true, progress: {
      status: progressStatus, added_at: null, review_count: 0, correct_count: 0, last_reviewed_at: null, next_review_at: null,
    } });
  });
  vi.spyOn(chrome.runtime, 'sendMessage').mockImplementation(send as never);
  await import('./reader');
  document.dispatchEvent(new Event('DOMContentLoaded'));
  await vi.waitFor(() => expect(document.querySelector('.unknown-word')).not.toBeNull());
  const word = document.querySelector<HTMLElement>('.word')!;
  word.click();
  await vi.waitFor(() => expect(document.querySelector('.flashcard-btn')).not.toBeNull());
  document.querySelector<HTMLButtonElement>('.flashcard-btn')!.click();
  await vi.waitFor(() => expect(send.mock.calls.some(([m]) => m.type === 'WORD_PROGRESS')).toBe(true));
  await Promise.resolve();
  expect(word.dataset.wordStatus).toBe('new');
  expect(document.querySelector('.reader-toast')?.textContent).toContain('Couldn’t save');

  // Retry the same word. This time the write went through but its reply was
  // lost, so progress confirms success and the optimistic mark should stay.
  await vi.advanceTimersByTimeAsync(4500);
  progressStatus = 'learning';
  word.click();
  await vi.waitFor(() => expect(document.querySelector('.flashcard-btn')).not.toBeNull());
  document.querySelector<HTMLButtonElement>('.flashcard-btn')!.click();
  await vi.waitFor(() => expect(send.mock.calls.filter(([m]) => m.type === 'WORD_PROGRESS')).toHaveLength(2));
  await Promise.resolve();
  expect(word.dataset.wordStatus).toBe('learning');
  expect(document.querySelector('.reader-toast')).toBeNull();
});
