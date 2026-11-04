import { beforeEach, expect, it, vi } from 'vitest';
import type { BackgroundMessage, WordProgress } from './messages';

const askBackground = vi.hoisted(() => vi.fn());
vi.mock('./messages', async (original) => ({ ...(await original<typeof import('./messages')>()), askBackground }));

// vi.mock is hoisted above this import, so the popup gets the mock.
import { appendWordProgress, createWordPopup, progressTooltip } from './wordPopup';

const header = (wordText: string, root: string) =>
  createWordPopup(wordText, { id: 1, root, translation: 'x' }, null).querySelector('.popup-header')!.textContent;

it('shows the form tapped, then the dictionary form', () => {
  expect(header('charlan', 'charlar')).toBe('charlan (charlar)');
});

it('shows one form when they differ only in case', () => {
  expect(header('Perro', 'perro')).toBe('perro');
});

const progress = (fields: Partial<WordProgress> = {}): WordProgress => ({
  status: 'learning', added_at: '2026-11-04T10:00:00Z', review_count: 0, correct_count: 0,
  last_reviewed_at: null, next_review_at: null, ...fields,
});

it('counts reviews in the tooltip, with the next one for a learning word', () => {
  expect(progressTooltip(progress())).toBe('No reviews');
  expect(progressTooltip(progress({ status: 'known', review_count: 1 }))).toBe('1 review');
  const inTwoWeeks = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString();
  expect(progressTooltip(progress({ review_count: 3, next_review_at: inTwoWeeks }))).toBe('3 reviews · next review in 2 weeks');
});

/** Answers WORD_PROGRESS with `states` in turn, RATE_WORD with `rated`. */
function answer(states: WordProgress[], rated: unknown = { ok: true, status: 'applied' }) {
  askBackground.mockImplementation(async (message: BackgroundMessage) =>
    message.type === 'RATE_WORD' ? rated : { ok: true, progress: states.length > 1 ? states.shift() : states[0] });
}

async function popupFor(wordId = 7) {
  const popup = createWordPopup('gemela', { id: wordId, root: 'gemela', translation: 'twin' }, null);
  document.body.replaceChildren(popup);
  appendWordProgress(popup, wordId);
  await vi.waitFor(() => expect(popup.querySelector('.progress-mark')).not.toBeNull());
  return popup;
}

beforeEach(() => {
  askBackground.mockReset();
});

it('shows the status alone, its reviews on hover, and two thumbs', async () => {
  answer([progress()]);
  const popup = await popupFor();
  const line = popup.querySelector('.word-progress')!;
  expect(line.textContent).toBe('Learning');
  expect(line.querySelector('.progress-mark')!.getAttribute('title')).toBe('No reviews');
  expect(Array.from(line.querySelectorAll('.rate-btn')).map((b) => b.getAttribute('aria-label')))
    .toEqual(['Knew it: review it later', 'Didn’t know it: review it sooner']);
});

it('rates the word, then shows its new progress', async () => {
  answer([progress(), progress({ review_count: 1, correct_count: 1 })]);
  const popup = await popupFor();
  const up = popup.querySelector<HTMLButtonElement>('.rate-up')!;
  const clicks = vi.fn();
  document.body.addEventListener('click', clicks);
  up.click();

  expect(clicks).not.toHaveBeenCalled(); // the popup stays open
  expect(askBackground).toHaveBeenCalledWith({ type: 'RATE_WORD', wordId: 7, rating: 'up' });
  expect(up.getAttribute('aria-pressed')).toBe('true');
  expect(Array.from(popup.querySelectorAll<HTMLButtonElement>('.rate-btn')).every((b) => b.disabled)).toBe(true);
  await vi.waitFor(() => expect(popup.querySelector('.progress-mark')!.getAttribute('title')).toBe('1 review'));
});

it('shows a known word rated down as learning again', async () => {
  answer([progress({ status: 'known' }), progress({ status: 'learning' })], { ok: true, status: 'relearning' });
  const popup = await popupFor();
  expect(popup.querySelector('.progress-mark')!.textContent).toBe('Known');
  popup.querySelector<HTMLButtonElement>('.rate-down')!.click();
  await vi.waitFor(() => expect(popup.querySelector('.progress-mark')!.textContent).toBe('Learning'));
  expect(popup.querySelector('.progress-mark')!.className).toBe('progress-mark progress-learning');
});

it('lets the user try again after a failed rating', async () => {
  answer([progress()], { ok: false, error: 'HTTP 500' });
  const popup = await popupFor();
  const down = popup.querySelector<HTMLButtonElement>('.rate-down')!;
  down.click();
  await vi.waitFor(() => expect(down.disabled).toBe(false));
  expect(down.getAttribute('aria-pressed')).toBe('false');
});

it('says so when the card was already rated today', async () => {
  answer([progress()], { ok: true, status: 'rated_today' });
  const popup = await popupFor();
  popup.querySelector<HTMLButtonElement>('.rate-up')!.click();
  await vi.waitFor(() => expect(popup.querySelector('.rate-up')!.getAttribute('title')).toBe('Already rated today'));
  expect(popup.querySelector('.rate-up')!.getAttribute('aria-pressed')).toBe('false');
});
