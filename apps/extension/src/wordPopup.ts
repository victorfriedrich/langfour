// wordPopup.ts
//
// The reader's word popup: the dictionary form, its translations, how the
// user's reviews of it went, and room for an "Add to flashcards" button.
// Built here so other pages (chatgptHighlight.ts) show the same popup; each
// page places it and styles it (reader.css, chatgptPopup.css).

import { askBackground, RateWordResponse, WordProgress, WordProgressResponse, WordRating } from './messages';
import { attachSpeakButton, SPEAKER_ICON } from './speak';
import type { Translation } from './translate';

export type PopupTranslation = Pick<Translation, 'id' | 'root' | 'translation'>;

// Create a loading popup element.
export function createLoadingPopup(wordText: string): HTMLDivElement {
  const popup = document.createElement('div');
  popup.className = 'word-popup loading-popup';
  popup.innerHTML = `
    <div class="sheet-handle" aria-hidden="true"></div>
    <div class="popup-header"></div>
    <div class="loading-content"><div class="spinner small"></div></div>
  `;
  (popup.querySelector('.popup-header') as HTMLElement).textContent = wordText;
  return popup;
}

export function createMessagePopup(wordText: string, message: string): HTMLDivElement {
  const popup = document.createElement('div');
  popup.className = 'word-popup';
  popup.innerHTML = `
    <div class="sheet-handle" aria-hidden="true"></div>
    <div class="popup-header"></div>
    <div class="popup-message"></div>
  `;
  (popup.querySelector('.popup-header') as HTMLElement).textContent = wordText;
  (popup.querySelector('.popup-message') as HTMLElement).textContent = message;
  return popup;
}

// Create a word popup element with translations.
export function createWordPopup(
  wordText: string,
  translation: PopupTranslation,
  language: string | null,
  action?: HTMLElement,
): HTMLDivElement {
  const popup = document.createElement('div');
  popup.className = 'word-popup';
  popup.innerHTML = '<div class="sheet-handle" aria-hidden="true"></div>';

  // The form tapped, then the dictionary form a flashcard would hold:
  // "charlan (charlar)".
  const header = document.createElement('div');
  header.className = 'popup-header';
  const headword = translation.root || wordText;
  // Only when they differ by more than case: not "Perro (perro)" at the
  // start of a sentence.
  header.textContent = headword.toLowerCase() === wordText.toLowerCase() ? headword : `${wordText} (${headword})`;
  // Pronounces the word on the line above, right after it.
  if (language) {
    const speakButton = document.createElement('button');
    speakButton.className = 'speak-btn';
    speakButton.setAttribute('aria-label', `Pronounce ${headword}`);
    speakButton.title = 'Pronounce';
    speakButton.innerHTML = SPEAKER_ICON;
    attachSpeakButton(speakButton, headword, language);
    header.appendChild(speakButton);
  }
  popup.appendChild(header);

  // The translations are alternatives of equal standing, not a best guess
  // followed by lesser ones.
  const translationsContainer = document.createElement('div');
  translationsContainer.className = 'translations-container';
  const options = (translation.translation ?? '').split(',').map((t: string) => t.trim()).filter(Boolean);
  if (options.length) {
    for (const text of options) {
      const translationEl = document.createElement('span');
      translationEl.className = 'translation';
      translationEl.textContent = text;
      translationsContainer.appendChild(translationEl);
    }
  } else {
    translationsContainer.innerHTML = '<span class="translation">No translation available</span>';
  }
  popup.appendChild(translationsContainer);

  // "Add to flashcards" for a new word; the caller decides and saves.
  if (action) popup.appendChild(action);
  return popup;
}

const DAY_MS = 24 * 60 * 60 * 1000;
// English, like the rest of the extension's interface.
const dateFormat = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short' });
const dateFormatWithYear = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' });
const relativeFormat = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

function formatDate(iso: string): string {
  const date = new Date(iso);
  return (date.getFullYear() === new Date().getFullYear() ? dateFormat : dateFormatWithYear).format(date);
}

/** "today", "3 days ago", "in 2 weeks": whole days, then weeks, months and years. */
function formatRelative(iso: string): string {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / DAY_MS);
  const abs = Math.abs(days);
  if (abs < 7) return relativeFormat.format(days, 'day');
  if (abs < 31) return relativeFormat.format(Math.round(days / 7), 'week');
  if (abs < 365) return relativeFormat.format(Math.round(days / 30), 'month');
  return relativeFormat.format(Math.round(days / 365), 'year');
}

function nextReviewText(iso: string): string {
  const due = new Date(iso).getTime();
  if (due > Date.now()) return `next review ${formatRelative(iso)}`;
  return Date.now() - due < DAY_MS ? 'due now' : `due since ${formatDate(iso)}`;
}

// Thumbs, drawn like the speaker icon.
const THUMB_UP_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>';
const THUMB_DOWN_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>';

/** The status's hover text: "No reviews", "3 reviews · next review in 2 weeks". */
export function progressTooltip(progress: WordProgress): string {
  const count = progress.review_count;
  const parts = [count === 0 ? 'No reviews' : `${count} ${count === 1 ? 'review' : 'reviews'}`];
  if (count > 0 && progress.status === 'learning' && progress.next_review_at) {
    parts.push(nextReviewText(progress.next_review_at));
  }
  return parts.join(' · ');
}

function showProgress(mark: HTMLElement, progress: WordProgress): void {
  // The status carries the word's own mark from the text, so the sheet
  // reads as being about the highlight that was tapped.
  mark.className = `progress-mark progress-${progress.status}`;
  mark.textContent = progress.status === 'known' ? 'Known' : 'Learning';
  mark.title = progressTooltip(progress);
}

/**
 * For a word the user is learning or knows: its status, with how its reviews
 * went on hover, and two thumbs that move its card up or down the schedule
 * (rate_word in apps/api/practice.py). Filled in once word_progress answers.
 */
export function appendWordProgress(popup: HTMLElement, wordId: number): void {
  // Under the word, like the byline under an article's title.
  const section = document.createElement('div');
  section.className = 'word-progress';
  const header = popup.querySelector('.popup-header');
  if (header) header.after(section);
  else popup.appendChild(section);

  void askBackground<WordProgressResponse>({ type: 'WORD_PROGRESS', wordId }).then((response) => {
    if (!response?.ok || !response.progress) {
      section.remove();
      return;
    }
    const mark = document.createElement('span');
    showProgress(mark, response.progress);
    section.append(mark, ratingButtons(wordId, mark));
  });
}

function ratingButtons(wordId: number, mark: HTMLElement): HTMLElement {
  const group = document.createElement('span');
  group.className = 'rating';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Rate this word');
  const buttons = ([
    ['up', THUMB_UP_ICON, 'Knew it: review it later'],
    ['down', THUMB_DOWN_ICON, 'Didn’t know it: review it sooner'],
  ] as const).map(([rating, icon, label]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `rate-btn rate-${rating}`;
    button.title = label;
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-pressed', 'false');
    button.innerHTML = icon;
    button.addEventListener('click', (event) => {
      // The popup closes on a click elsewhere; this one stays inside it.
      event.stopPropagation();
      rate(rating, button);
    });
    return button;
  });

  const rate = (rating: WordRating, pressed: HTMLButtonElement) => {
    for (const b of buttons) b.disabled = true;
    pressed.setAttribute('aria-pressed', 'true');
    void askBackground<RateWordResponse>({ type: 'RATE_WORD', wordId, rating }).then((response) => {
      if (!response?.ok) {
        // Nothing changed: let them try again.
        pressed.setAttribute('aria-pressed', 'false');
        for (const b of buttons) b.disabled = false;
        return;
      }
      if (response.status === 'rated_today') {
        pressed.setAttribute('aria-pressed', 'false');
        for (const b of buttons) b.title = 'Already rated today';
        return;
      }
      // The review count and next review moved; a known word may be learning again.
      void askBackground<WordProgressResponse>({ type: 'WORD_PROGRESS', wordId }).then((progress) => {
        if (progress?.ok && progress.progress) showProgress(mark, progress.progress);
      });
    });
  };

  group.append(...buttons);
  return group;
}
