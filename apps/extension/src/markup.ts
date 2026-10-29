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

export function getPopupHTML(offsetBottom: number, word: string) {
  // The tapped word and a bar where the translation will go, so the popup
  // opens at about its final size instead of growing when it arrives.
  return `
    <div class="${subPopupClassName}">
      <div class="sub-tr-popup-container" style="margin-bottom: ${offsetBottom}px;">
        <div class="${subLoadingClassName}" role="status" aria-label="Translating">
          <p>${escapeHTML(word)}</p>
          <span class="sub-tr-skeleton"></span>
        </div>
      </div>
    </div>
  `;
}

/**
 * "caía → caer" when the tapped form is not the dictionary form. A noun's
 * dictionary form carries its article ("la diversión", "l'eau"), which is
 * the same word, so that shows as the dictionary form alone.
 */
function formAndRoot(word: string, root: string | null | undefined): string {
  if (!root) return word;
  const tapped = word.toLowerCase();
  const dictionary = root.toLowerCase();
  const sameWord = dictionary === tapped || dictionary.endsWith(` ${tapped}`) || dictionary.endsWith(`'${tapped}`);
  return sameWord ? root : `${word} → ${root}`;
}

export function getTranslationHTML(translations: Translation[], word: string, offerSaving: boolean) {
  // prettier-ignore
  return `
    <div class="sub-tr-popup-content">
      <div class="sub-tr-dict">
        ${translations.map((translation) => `
          <div class="sub-tr-dict-item">
            <div class="sub-tr-dict-item-title">
              <div class="nomargin">
                <p>${escapeHTML(formAndRoot(word, translation.root))}</p>
                <span class="sub-tr-dict-item-text">${escapeHTML(translation.translation ?? '')}</span>
              </div>
              ${offerSaving && translation.id > 0 ? `<button class="sub-tr-plus-button" data-id="${escapeHTML(translation.id)}" aria-label="Add ${escapeHTML(translation.root ?? translation.translation)} to flashcards" title="Add to flashcards">+</button>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

export function getSignInPromptHTML(word: string) {
  // prettier-ignore
  return `
    <div class="sub-tr-popup-content">
      <div class="sub-tr-dict-item">
        <p>${escapeHTML(word)}</p>
        <span class="sub-tr-dict-item-text">Sign in to Langfour to see translations.</span>
        <button class="sub-tr-sign-in-button">Sign in</button>
      </div>
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
