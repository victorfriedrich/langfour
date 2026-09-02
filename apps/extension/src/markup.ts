import { Translation } from './translate';
import { WordMask } from './textProcessing/wrapNodeWords';

export const popupWidth = 100;
export const popupHeight = 20;
export const popupVerticalOffset = 35;
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

export function getPopupHTML(offsetBottom: number) {
  console.log(`Popup offsetBottom: ${offsetBottom}`);
  return `
    <div class="${subPopupClassName}">
      <div class="sub-tr-popup-container" style="margin-bottom: ${offsetBottom}px;">
        <div class="${subLoadingClassName}">

        </div>
      </div>
    </div>
  `;
}

export function getTranslationHTML(translations: Translation[]) {
  // prettier-ignore
  return `
    <div class="sub-tr-popup-content">
      <div class="sub-tr-dict">
        ${translations.map((translation) => `
          <div class="sub-tr-dict-item">
            <div class="sub-tr-dict-item-title">
              <div class="nomargin">
                <p>${escapeHTML(translation.root ?? 'no root')}</p>
                <span class="sub-tr-dict-item-text">${escapeHTML(translation.translation ?? '')}</span>
              </div>
              <button class="sub-tr-plus-button" data-id="${escapeHTML(translation.id)}" aria-label="Add word ${escapeHTML(translation.translation)}">+</button>
            </div>
          </div>
        `).join('')}
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
