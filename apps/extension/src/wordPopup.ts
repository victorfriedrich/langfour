// wordPopup.ts
//
// The reader's word popup: the dictionary form, its translations, how the
// user's reviews of it went, and room for an "Add to flashcards" button.
// Built here so other pages (chatgptHighlight.ts) show the same popup; each
// page places it and styles it (reader.css, chatgptPopup.css).

import { askBackground, WordProgressResponse } from './messages';
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
export function createWordPopup(wordText: string, translation: PopupTranslation, action?: HTMLElement): HTMLDivElement {
  const popup = document.createElement('div');
  popup.className = 'word-popup';
  popup.innerHTML = '<div class="sheet-handle" aria-hidden="true"></div>';

  // The dictionary form ("la fechoría", "creer"), not the form tapped: that
  // is what a flashcard would hold.
  const header = document.createElement('div');
  header.className = 'popup-header';
  header.textContent = translation.root || wordText;
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

/**
 * For a word the user is learning or knows: one line on when it was added
 * and how its reviews went, filled in once word_progress answers.
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
    const progress = response.progress;
    // The status carries the word's own mark from the text, so the sheet
    // reads as being about the highlight that was tapped.
    const mark = document.createElement('span');
    mark.className = `progress-mark progress-${progress.status}`;
    mark.textContent = progress.status === 'known' ? 'Known' : 'Learning';

    const parts: string[] = [];
    if (progress.added_at) parts.push(`added ${formatDate(progress.added_at)}`);
    if (progress.review_count === 0) {
      if (progress.status === 'learning') parts.push('not reviewed yet');
    } else {
      parts.push(`${progress.review_count} ${progress.review_count === 1 ? 'review' : 'reviews'}`);
      if (progress.status === 'learning' && progress.next_review_at) parts.push(nextReviewText(progress.next_review_at));
    }
    section.append(mark, ...parts.map((part) => ` · ${part}`));
  });
}
