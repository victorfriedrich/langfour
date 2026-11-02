import { Translation } from './translate';
import { WordMask } from './textProcessing/wrapNodeWords';

export const popupWidth = 100;
export const popupHeight = 20;
export const subContainerClassName = 'sub-tr-text';
export const subWordClassName = 'sub-tr-word';
export const subWordMaskClassName = 'sub-tr-mask';
export const subWordMaskHiddenClassName = 'sub-tr-mask-hidden';
export const subWordHiddenClassName = 'sub-tr-word-hidden';
export const subPopupWrapperClassName = 'sub-tr-popup-wrapper';
export const subPopupClassName = 'sub-tr-popup';
export const subWordReveal = 'sub-tr-reveal';
export const subLoadingClassName = 'sub-tr-loading';

function escapeHTML(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    '\'': '&#039;',
  })[character]!);
}

export function getSubtitlesWordHTML(word: string) {
  return `<span class="${subWordClassName}">${escapeHTML(word)}</span>`;
}

export function getSubtitlesHiddenWordHTML(word: string) {
  return `<span class="${subWordClassName} ${subWordHiddenClassName}">${escapeHTML(word)}</span>`;
}

export function getPopupHTML() {
  // Bars where the dictionary form and the translation will go, so the popup
  // opens at its final size instead of growing when they arrive.
  return `
    <div class="${subPopupClassName}">
      <div class="${subLoadingClassName}" role="status" aria-label="Translating">
        <span class="sub-tr-skeleton sub-tr-skeleton-root"></span>
        <span class="sub-tr-skeleton sub-tr-skeleton-text"></span>
      </div>
    </div>
  `;
}

const PLUS_ICON =
  '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M9 2.5v13M2.5 9h13"></path></svg>';

export function getTranslationHTML(translations: Translation[], word: string, offerSaving: boolean) {
  // The dictionary form alone, not "vas → ir": the tapped form is highlighted
  // in the caption right below the popup.
  // prettier-ignore
  return `
    <div class="sub-tr-popup-content">
      ${translations.map((translation) => {
        const headword = translation.root || word;
        return `
          <div class="sub-tr-dict-item">
            <div class="sub-tr-dict-item-words">
              <div class="sub-tr-dict-item-root">${escapeHTML(headword)}</div>
              <div class="sub-tr-dict-item-text">${escapeHTML(translation.translation ?? '')}</div>
            </div>
            ${offerSaving && translation.id > 0 ? `<button type="button" class="sub-tr-plus-button" data-id="${escapeHTML(translation.id)}" aria-label="Add ${escapeHTML(headword)} to flashcards" title="Add to flashcards">${PLUS_ICON}</button>` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

export function getSignInPromptHTML(word: string) {
  // prettier-ignore
  return `
    <div class="sub-tr-popup-content">
      <div class="sub-tr-dict-item-words">
        <div class="sub-tr-dict-item-root">${escapeHTML(word)}</div>
        <div class="sub-tr-dict-item-text">Sign in to Langfour to see translations.</div>
      </div>
      <button type="button" class="sub-tr-sign-in-button">Sign in</button>
    </div>
  `;
}

export function getWordMaskHTML(targetElementRect: DOMRect, wordMask: WordMask) {
  const { rect, word, isHidden } = wordMask;

  return `
    <div
      class="${subWordMaskClassName} ${isHidden ? subWordMaskHiddenClassName : ''}"
      data-word="${escapeHTML(word)}"
      style=" 
        top: ${rect.top - targetElementRect.top + 1}px;
        left: ${rect.left - targetElementRect.left}px;  
        width: ${rect.width}px; 
        height: ${rect.height - 2}px;
      "/>
  `;
}

export function getWordWrapperHTML(word: string) {
  return `
    <span class="${subContainerClassName}">${word}</span>
  `;
}
