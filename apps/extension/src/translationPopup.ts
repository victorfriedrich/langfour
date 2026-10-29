import {
  getPopupHTML,
  getSignInPromptHTML,
  getTranslationHTML,
  subLoadingClassName,
  subPopupClassName,
  subPopupWrapperClassName,
} from './markup';
import translationPopupStyles from 'bundle-text:./translationPopup.css';
import { positionElement } from './utils';
import { sanitizeHTML } from './sanitizeHTML';
import { Translation } from './translate';
import { sendToBackground } from './messages';

export function insertTranslationPopup(
  targetEl: HTMLElement,
  containerEl: HTMLElement,
  offsetBottom: number,
  onClose: () => void,
): HTMLElement {
  const shadowDomWrapperEl = document.createElement('div');
  shadowDomWrapperEl.classList.add(subPopupWrapperClassName);
  const shadow = shadowDomWrapperEl.attachShadow({ mode: 'open' });
  const styleEl = document.createElement('style');
  styleEl.textContent = translationPopupStyles as unknown as string;

  // The popup lives inside the video player; keep its taps and clicks from
  // bubbling up to the player, which would pause or toggle its controls.
  for (const type of ['click', 'touchstart', 'touchend']) {
    shadowDomWrapperEl.addEventListener(type, (event) => event.stopPropagation());
  }

  shadow.innerHTML = sanitizeHTML(getPopupHTML(offsetBottom, targetEl.dataset['word'] ?? targetEl.innerText));
  shadow.appendChild(styleEl);
  containerEl.appendChild(shadowDomWrapperEl);

  const popupEl = shadow.querySelector(`.${subPopupClassName}`) as HTMLElement;
  positionElement(popupEl, targetEl, containerEl);
  // Re-place it as soon as its size changes (the translation arriving), in
  // the same frame, rather than on index.ts's 100 ms timer.
  const resizeObserver = new ResizeObserver(() => {
    if (!popupEl.isConnected) return resizeObserver.disconnect();
    positionElement(popupEl, targetEl, containerEl);
  });
  resizeObserver.observe(popupEl);
  popupEl.querySelector('.sub-tr-plus-button')?.addEventListener('click', onClose);
  return popupEl;
}

function postToContentScript(data: { wordId: string }) {
  // In Safari this script runs as a content script (see contentScript.ts),
  // where chrome.runtime is available and the page bridge below is not
  // needed: its event.source check does not hold across worlds there.
  if (typeof chrome !== 'undefined' && chrome.runtime?.id) {
    sendToBackground<{ success: boolean; error?: string }>(
      { type: 'ADD_WORD_TO_USERWORDS', wordId: data.wordId },
      (response) => {
        if (chrome.runtime.lastError || !response?.success) {
          console.error('Error adding word:', chrome.runtime.lastError ?? response?.error);
        }
      },
    );
    return;
  }
  window.postMessage({
    source: 'translationPopup',
    payload: data
  }, window.location.origin);
}

export function insertTranslationResult(
  translationPopupEl: HTMLElement,
  translations: Translation,
  word: string,
  offerSaving: boolean,
  hideTranslationPopup: () => void
) {
  const html = getTranslationHTML([translations], word, offerSaving);
  const loaderEl = translationPopupEl.querySelector(`.${subLoadingClassName}`);
  loaderEl?.insertAdjacentHTML('afterend', sanitizeHTML(html));
  loaderEl?.remove();

  // Attach event listeners to the new buttons
  translationPopupEl.querySelectorAll('.sub-tr-plus-button').forEach(button => {
    button.addEventListener('click', async () => {
      const wordId = button.getAttribute('data-id');
      if (wordId) {
        postToContentScript({ wordId });
        // Show that it was saved before the popup goes away.
        button.textContent = '✓';
        button.classList.add('sub-tr-saved');
        button.setAttribute('aria-label', 'Added to flashcards');
        (button as HTMLButtonElement).disabled = true;
        // Unless another word's popup has replaced this one meanwhile.
        setTimeout(() => button.isConnected && hideTranslationPopup(), 600);

      } else {
        console.error('No word ID found');
      }
    });
  });
}

// Shown instead of a translation when there is no session: the API only
// translates for signed-in users.
export function insertSignInPrompt(translationPopupEl: HTMLElement, word: string, onClose: () => void) {
  const loaderEl = translationPopupEl.querySelector(`.${subLoadingClassName}`);
  loaderEl?.insertAdjacentHTML('afterend', sanitizeHTML(getSignInPromptHTML(word)));
  loaderEl?.remove();
  translationPopupEl.querySelector('.sub-tr-sign-in-button')?.addEventListener('click', () => {
    onClose();
    document.dispatchEvent(new CustomEvent('open-sign-in'));
  });
}

export function hideTranslationPopup() {
  const popupEl = document.querySelector(`.${subPopupWrapperClassName}`);
  popupEl?.remove();
}
